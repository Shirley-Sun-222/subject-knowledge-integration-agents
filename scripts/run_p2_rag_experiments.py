from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings
from backend.app.db import init_db
from backend.app.runtime.store import state_store
from backend.app.services import rag
from backend.app.services.embedding import embedding_service
from backend.app.services.llm import llm_client
from backend.app.services.textbooks import import_textbook_file
from backend.app.utils.ids import new_id
from backend.app.utils.text import chunk_text, estimate_tokens
from scripts.run_rag_benchmark import evaluate_response, load_questions, ratio

SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt", ".docx"}
DEFAULT_SUBSET = ["03_生理学.pdf", "04_医学微生物学.pdf", "05_病理学.pdf"]
EXPERIMENT_WORKSPACE = "p2_rag_official"
DEFAULT_CHUNK_SIZES = [300, 500, 700, 900]
CHUNK_OVERLAP = 90

VARIANTS = [
    {
        "id": "vector_baseline",
        "label": "纯向量检索基线",
        "use_hybrid": False,
        "use_guard": False,
        "enforce_answer_contract": False,
    },
    {
        "id": "hybrid_retrieval",
        "label": "向量 + BM25 混合检索",
        "use_hybrid": True,
        "use_guard": False,
        "enforce_answer_contract": False,
    },
    {
        "id": "hybrid_with_guard",
        "label": "混合检索 + 查询重叠保护",
        "use_hybrid": True,
        "use_guard": True,
        "enforce_answer_contract": False,
    },
    {
        "id": "full_robust_stack",
        "label": "完整稳健性方案",
        "use_hybrid": True,
        "use_guard": True,
        "enforce_answer_contract": True,
    },
]


def sample_files(sample_dir: Path, filenames: list[str] | None = None) -> list[Path]:
    files = sorted(path for path in sample_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)
    if filenames is None:
        return files
    requested = set(filenames)
    selected = [path for path in files if path.name in requested]
    missing = requested - {path.name for path in selected}
    if missing:
        raise FileNotFoundError(f"Missing textbooks: {sorted(missing)}")
    return selected


@contextmanager
def isolated_runtime(run_root: Path, *, ocr_max_pages: int | None, enable_llm: bool) -> Iterable[None]:
    originals = {
        "database_url": settings.database_url,
        "upload_dir": settings.upload_dir,
        "generated_dir": settings.generated_dir,
        "index_dir": settings.index_dir,
        "ocr_max_pages": settings.ocr_max_pages,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
    }
    try:
        object.__setattr__(settings, "database_url", f"sqlite:///{run_root / 'app.db'}")
        object.__setattr__(settings, "upload_dir", run_root / "uploads")
        object.__setattr__(settings, "generated_dir", run_root / "generated")
        object.__setattr__(settings, "index_dir", run_root / "indexes")
        if ocr_max_pages is not None:
            object.__setattr__(settings, "ocr_max_pages", ocr_max_pages)
        if not enable_llm:
            object.__setattr__(settings, "llm_base_url", "")
            object.__setattr__(settings, "llm_api_key", "")
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        settings.generated_dir.mkdir(parents=True, exist_ok=True)
        settings.index_dir.mkdir(parents=True, exist_ok=True)
        embedding_service._model = None
        embedding_service._model_failed = False
        yield
    finally:
        embedding_service._model = None
        embedding_service._model_failed = False
        for key, value in originals.items():
            object.__setattr__(settings, key, value)


def import_textbooks(sample_dir: Path, files: list[Path], workspace_id: str) -> list[dict[str, Any]]:
    init_db()
    imported = []
    for path in files:
        textbook = import_textbook_file(path, original_filename=path.name, workspace_id=workspace_id)
        imported.append(
            {
                "id": textbook["id"],
                "filename": textbook["filename"],
                "title": textbook["title"],
                "status": textbook["status"],
                "chapters": len(textbook.get("chapters", [])),
                "total_chars": textbook.get("total_chars", 0),
                "source_path": str(path.relative_to(sample_dir.parent)),
            }
        )
    return imported


def rebuild_chunks(workspace_id: str, *, chunk_size: int, overlap: int) -> dict[str, Any]:
    chapters = state_store.list_all_chapters(workspace_id)
    chunk_rows = []
    for chapter in chapters:
        pieces = chunk_text(chapter["content"], size=chunk_size, overlap=overlap)
        vectors = embedding_service.embed(pieces)
        for index, text in enumerate(pieces):
            chunk_rows.append(
                {
                    "id": new_id("chunk"),
                    "textbook_id": chapter["textbook_id"],
                    "chapter_id": chapter["id"],
                    "chunk_index": index,
                    "text": text,
                    "page_start": chapter["page_start"],
                    "char_count": len(text),
                    "embedding": json.dumps(vectors[index], ensure_ascii=False),
                }
            )
    state_store.replace_chunks(workspace_id, chunk_rows)
    return {
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "chunk_count": len(chunk_rows),
        "chapter_count": len(chapters),
        "textbook_count": state_store.count_completed_textbooks(workspace_id),
        "using_fallback_embedding": embedding_service.using_fallback,
        "llm_configured": llm_client.is_configured(workspace_id),
    }


def query_variant(question: str, variant: dict[str, Any], *, workspace_id: str, top_k: int) -> dict[str, Any]:
    started = time.perf_counter()
    rows = state_store.list_chunks_with_context(workspace_id)
    if not rows:
        return {"answer": "当前知识库中未找到相关信息", "citations": [], "elapsed_ms": 0, "token_estimate": estimate_tokens([question])}

    vector_scores = rag._vector_scores(question, rows)
    bm25_scores = rag._bm25_scores(question, rows) if variant["use_hybrid"] else {row["id"]: 0.0 for row in rows}
    ranked = []
    for row in rows:
        vector_score = vector_scores.get(row["id"], 0.0)
        keyword_score = bm25_scores.get(row["id"], 0.0)
        if variant["use_hybrid"] and embedding_service.using_fallback and keyword_score <= 0:
            continue
        score = (0.68 * vector_score + 0.32 * keyword_score) if variant["use_hybrid"] else vector_score
        if score >= 0.12:
            ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    top = [(score, row) for score, row in ranked[:top_k] if score > 0]

    if not top:
        return {
            "answer": "当前知识库中未找到相关信息",
            "citations": [],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "token_estimate": estimate_tokens([question]),
        }

    if variant["use_guard"] and not rag._has_specific_query_overlap(question, top):
        return {
            "answer": "当前知识库中未找到相关信息",
            "citations": [],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "token_estimate": estimate_tokens([question]),
        }

    answer_result = _answer_with_variant_contract(question, top, workspace_id=workspace_id, enforce_contract=variant["enforce_answer_contract"])
    citations = [
        {
            "textbook": row["textbook"],
            "chapter": row["chapter"],
            "page": row["page_start"],
            "relevance_score": round(float(score), 4),
            "chunk_id": row["id"],
            "text": row["text"],
        }
        for score, row in top
    ]
    elapsed_ms = int((time.perf_counter() - started) * 1000) + int(answer_result.get("elapsed_ms", 0))
    token_estimate = estimate_tokens([question, *(row["text"] for _, row in top), answer_result["answer"]])
    return {
        "answer": answer_result["answer"],
        "citations": citations,
        "elapsed_ms": elapsed_ms,
        "token_estimate": token_estimate,
    }


def _answer_with_variant_contract(question: str, top: list[tuple[float, dict[str, Any]]], *, workspace_id: str, enforce_contract: bool) -> dict[str, Any]:
    if enforce_contract:
        return rag._answer_with_context(question, top, workspace_id=workspace_id)

    if llm_client.is_configured(workspace_id):
        context = "\n\n".join(
            f"[{index}] {row['textbook']} / {row['chapter']} / 第 {row['page_start']} 页\n{row['text']}"
            for index, (_, row) in enumerate(top, start=1)
        )
        result = llm_client.complete_text(
            "你是教材问答助手。请基于上下文简洁作答，不需要显式给出引用格式。",
            f"问题: {question}\n\n上下文:\n{context}",
            workspace_id=workspace_id,
        )
        if result.get("data"):
            return {"answer": result["data"], "elapsed_ms": result.elapsed_ms}

    first = top[0][1]
    answer = f"{first['text'][:220]}..."
    return {"answer": answer, "elapsed_ms": 0}


def run_variant_suite(
    questions: list[dict[str, Any]],
    variant_defs: list[dict[str, Any]],
    *,
    workspace_id: str,
    top_k: int,
    chunk_size: int,
    overlap: int,
    dataset_label: str,
    textbook_names: list[str],
) -> dict[str, Any]:
    chunk_meta = rebuild_chunks(workspace_id, chunk_size=chunk_size, overlap=overlap)
    variant_results = []
    for variant in variant_defs:
        output = []
        started = time.perf_counter()
        for item in questions:
            response = query_variant(item["question"], variant, workspace_id=workspace_id, top_k=top_k)
            evaluation = evaluate_response(item, response)
            output.append(
                {
                    **evaluation,
                    "question": item["question"],
                    "answer": response["answer"],
                    "elapsed_ms": response["elapsed_ms"],
                    "token_estimate": response["token_estimate"],
                    "citations": [
                        {
                            "textbook": citation["textbook"],
                            "chapter": citation["chapter"],
                            "page": citation["page"],
                            "relevance_score": citation["relevance_score"],
                        }
                        for citation in response["citations"]
                    ],
                }
            )
        variant_results.append(
            _summarize_variant(
                output,
                variant=variant,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                dataset_label=dataset_label,
                textbook_names=textbook_names,
                chunk_meta=chunk_meta,
            )
        )
    return {
        "dataset": dataset_label,
        "textbooks": textbook_names,
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "variant_results": variant_results,
        "markdown_table": render_variant_table(variant_results),
    }


def _summarize_variant(
    rows: list[dict[str, Any]],
    *,
    variant: dict[str, Any],
    elapsed_ms: int,
    dataset_label: str,
    textbook_names: list[str],
    chunk_meta: dict[str, Any],
) -> dict[str, Any]:
    positive = [row for row in rows if row["should_cite"]]
    negative = [row for row in rows if not row["should_cite"]]
    return {
        "variant_id": variant["id"],
        "variant_label": variant["label"],
        "dataset": dataset_label,
        "textbooks": textbook_names,
        "question_count": len(rows),
        "positive_question_count": len(positive),
        "negative_question_count": len(negative),
        "pass_rate": ratio(rows, "passed"),
        "citation_presence_score": ratio(positive, "has_citation"),
        "source_hint_score": ratio(positive, "citation_matches_source_hint"),
        "answer_term_score": ratio(positive, "answer_matches_expected_terms"),
        "rejection_score": ratio(negative, "correctly_rejected"),
        "category_pass_rate": {
            category: ratio([row for row in rows if row["category"] == category], "passed")
            for category in sorted({row["category"] for row in rows})
        },
        "avg_elapsed_ms": int(sum(row["elapsed_ms"] for row in rows) / len(rows)) if rows else 0,
        "total_token_estimate": sum(row["token_estimate"] for row in rows),
        "suite_elapsed_ms": elapsed_ms,
        "chunk_size": chunk_meta["chunk_size"],
        "chunk_overlap": chunk_meta["chunk_overlap"],
        "chunk_count": chunk_meta["chunk_count"],
        "using_fallback_embedding": chunk_meta["using_fallback_embedding"],
        "llm_configured": chunk_meta["llm_configured"],
        "results": rows,
    }


def render_variant_table(variant_results: list[dict[str, Any]]) -> str:
    lines = [
        "| 方案 | pass_rate | source_hint_score | rejection_score | avg_elapsed_ms | total_token_estimate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in variant_results:
        lines.append(
            f"| {result['variant_label']} | {result['pass_rate']:.3f} | {result['source_hint_score']:.3f} | {result['rejection_score']:.3f} | {result['avg_elapsed_ms']} | {result['total_token_estimate']} |"
        )
    return "\n".join(lines)


def run_chunk_sensitivity(
    questions: list[dict[str, Any]],
    *,
    workspace_id: str,
    chunk_sizes: list[int],
    top_k: int,
    dataset_label: str,
    textbook_names: list[str],
) -> dict[str, Any]:
    results = []
    for chunk_size in chunk_sizes:
        suite = run_variant_suite(
            questions,
            [VARIANTS[-1]],
            workspace_id=workspace_id,
            top_k=top_k,
            chunk_size=chunk_size,
            overlap=CHUNK_OVERLAP,
            dataset_label=dataset_label,
            textbook_names=textbook_names,
        )
        results.append(suite["variant_results"][0])
    return {
        "dataset": dataset_label,
        "textbooks": textbook_names,
        "chunk_results": results,
        "recommended_chunk_size": choose_best_chunk_size(results),
        "markdown_table": render_chunk_table(results),
    }


def choose_best_chunk_size(results: list[dict[str, Any]]) -> int:
    ordered = sorted(
        results,
        key=lambda item: (
            item["pass_rate"],
            item["source_hint_score"],
            item["rejection_score"],
            -item["avg_elapsed_ms"],
            -item["chunk_size"],
        ),
        reverse=True,
    )
    return int(ordered[0]["chunk_size"])


def render_chunk_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| chunk_size | pass_rate | source_hint_score | rejection_score | avg_elapsed_ms | total_token_estimate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            f"| {result['chunk_size']} | {result['pass_rate']:.3f} | {result['source_hint_score']:.3f} | {result['rejection_score']:.3f} | {result['avg_elapsed_ms']} | {result['total_token_estimate']} |"
        )
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the P2 official-medical RAG experiments.")
    parser.add_argument("--sample-dir", default="textbooks", help="Directory containing official textbooks.")
    parser.add_argument("--question-set", default="scripts/benchmark_sets/medical_official_questions.json", help="Medical benchmark JSON file.")
    parser.add_argument("--output-dir", default="data/generated/p2-rag-official", help="Directory for experiment outputs.")
    parser.add_argument("--mode", choices=["subset", "full", "all"], default="all", help="Run only the subset stage, only the full stage, or both.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieved chunks.")
    parser.add_argument("--ocr-max-pages", type=int, default=40, help="OCR page cap for import runs.")
    parser.add_argument("--enable-llm", action="store_true", help="Keep configured LLM enabled during experiments.")
    parser.add_argument("--subset-files", nargs="*", default=DEFAULT_SUBSET, help="Subset textbooks for quick tuning.")
    parser.add_argument("--chunk-sizes", nargs="*", type=int, default=DEFAULT_CHUNK_SIZES, help="Chunk sizes for the sensitivity study.")
    parser.add_argument("--final-chunk-size", type=int, default=None, help="Optional fixed chunk size for the full run.")
    args = parser.parse_args()

    sample_dir = (ROOT / args.sample_dir).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    questions = load_questions(args.question_set)
    subset_paths = sample_files(sample_dir, args.subset_files)
    full_paths = sample_files(sample_dir)

    subset_root = output_dir / "subset"
    full_root = output_dir / "full"

    imported_subset: list[dict[str, Any]] = []
    imported_full: list[dict[str, Any]] = []
    recommended_chunk_size = args.final_chunk_size or 700
    if args.mode in {"subset", "all"}:
        with isolated_runtime(subset_root / "runtime", ocr_max_pages=args.ocr_max_pages, enable_llm=args.enable_llm):
            imported_subset = import_textbooks(sample_dir, subset_paths, EXPERIMENT_WORKSPACE)
            subset_ablation = run_variant_suite(
                questions,
                VARIANTS,
                workspace_id=EXPERIMENT_WORKSPACE,
                top_k=args.top_k,
                chunk_size=700,
                overlap=CHUNK_OVERLAP,
                dataset_label="official_subset",
                textbook_names=[path.name for path in subset_paths],
            )
            subset_chunk = run_chunk_sensitivity(
                questions,
                workspace_id=EXPERIMENT_WORKSPACE,
                chunk_sizes=args.chunk_sizes,
                top_k=args.top_k,
                dataset_label="official_subset",
                textbook_names=[path.name for path in subset_paths],
            )
            recommended_chunk_size = subset_chunk["recommended_chunk_size"]
            write_json(subset_root / "ablation.json", subset_ablation)
            write_text(subset_root / "ablation-table.md", subset_ablation["markdown_table"])
            write_json(subset_root / "chunk-sensitivity.json", subset_chunk)
            write_text(subset_root / "chunk-sensitivity-table.md", subset_chunk["markdown_table"])

    if args.mode in {"full", "all"}:
        with isolated_runtime(full_root / "runtime", ocr_max_pages=args.ocr_max_pages, enable_llm=args.enable_llm):
            imported_full = import_textbooks(sample_dir, full_paths, EXPERIMENT_WORKSPACE)
            full_ablation = run_variant_suite(
                questions,
                VARIANTS,
                workspace_id=EXPERIMENT_WORKSPACE,
                top_k=args.top_k,
                chunk_size=recommended_chunk_size,
                overlap=CHUNK_OVERLAP,
                dataset_label="official_full",
                textbook_names=[path.name for path in full_paths],
            )
            write_json(full_root / "ablation.json", full_ablation)
            write_text(full_root / "ablation-table.md", full_ablation["markdown_table"])

    manifest_path = output_dir / "manifest.json"
    existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest = {
        "mode": args.mode,
        "question_set": str(Path(args.question_set)),
        "subset_files": [path.name for path in subset_paths],
        "full_files": [path.name for path in full_paths],
        "chunk_sizes": args.chunk_sizes,
        "recommended_chunk_size": recommended_chunk_size,
        "subset_imported": imported_subset or existing_manifest.get("subset_imported", []),
        "full_imported": imported_full or existing_manifest.get("full_imported", []),
        "outputs": {},
    }
    if args.mode in {"subset", "all"}:
        manifest["outputs"]["subset_ablation"] = str((subset_root / "ablation.json").relative_to(ROOT))
        manifest["outputs"]["subset_chunk_sensitivity"] = str((subset_root / "chunk-sensitivity.json").relative_to(ROOT))
    if args.mode in {"full", "all"}:
        manifest["outputs"]["full_ablation"] = str((full_root / "ablation.json").relative_to(ROOT))
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
