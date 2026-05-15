from __future__ import annotations

import json
import time
from collections import Counter

from ..db import utc_now
from ..runtime.store import state_store
from ..runtime.tasks import TaskContext, task_runner
from ..schemas import Citation, RagQueryResponse
from ..services.embedding import embedding_service
from ..services.llm import llm_client
from ..utils.ids import new_id
from ..utils.text import chunk_text, estimate_tokens, tokenize

GENERIC_QUERY_TERMS = {
    "什么",
    "为何",
    "为什么",
    "如何",
    "怎么",
    "多少",
    "今天",
    "通常",
    "哪些",
    "用于",
    "解决",
    "介绍",
    "工作",
    "系统",
    "推荐",
    "三家",
    "餐厅",
    "意思",
    "区别",
    "联系",
    "共同",
    "主题",
}


def enqueue_build_index(workspace_id: str = "global") -> tuple[dict, bool]:
    is_fresh, chapter_count = state_store.rag_index_freshness(workspace_id)
    if is_fresh:
        task = state_store.create_finished_task(
            workspace_id,
            "build_rag_index",
            "system",
            "global",
            phase="cache_hit",
            result_ref="rag-index:global",
            progress_current=chapter_count,
            progress_total=chapter_count,
        )
        return task, False
    return task_runner.enqueue(
        workspace_id,
        "build_rag_index",
        "system",
        "global",
        lambda context: _build_index_task(context, workspace_id=workspace_id),
    )


def _build_index_task(context: TaskContext, workspace_id: str = "global") -> dict:
    result = build_index(progress=context, workspace_id=workspace_id)
    return {
        "result_ref": "rag-index:global",
        "phase": "completed",
        "truncated": False,
    }


def build_index(progress: TaskContext | None = None, workspace_id: str = "global") -> dict:
    chapters = state_store.list_all_chapters(workspace_id)
    existing_entries = state_store.list_rag_index_entries(workspace_id)
    active_chapter_ids = {chapter["id"] for chapter in chapters}
    deleted_chapter_ids = [chapter_id for chapter_id in existing_entries if chapter_id not in active_chapter_ids]
    rebuild_targets = []
    reused_entries = 0

    for chapter in chapters:
        signature = state_store.rag_index_signature(chapter)
        entry = existing_entries.get(chapter["id"])
        if entry is not None and entry["chunk_signature"] == signature:
            reused_entries += 1
            continue
        rebuild_targets.append((chapter, signature))

    if progress is not None:
        progress.start("chunking_textbooks", progress_total=len(chapters))
    chunk_rows = []
    index_entries = []
    processed = 0
    for chapter in chapters:
        signature = state_store.rag_index_signature(chapter)
        entry = existing_entries.get(chapter["id"])
        if entry is not None and entry["chunk_signature"] == signature:
            processed += 1
            if progress is not None:
                progress.progress(
                    phase="reusing_index_chunks" if processed < len(chapters) else "writing_index",
                    progress_current=processed,
                    progress_total=len(chapters),
                )
            continue
        chunks = chunk_text(chapter["content"], size=700, overlap=90)
        vectors = embedding_service.embed(chunks)
        for index, text in enumerate(chunks):
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
        index_entries.append(
            {
                "chapter_id": chapter["id"],
                "textbook_id": chapter["textbook_id"],
                "chunk_signature": signature,
                "chunk_count": len(chunks),
                "built_at": utc_now(),
            }
        )
        processed += 1
        if progress is not None:
            progress.progress(
                phase="chunking_textbooks" if processed < len(chapters) else "writing_index",
                progress_current=processed,
                progress_total=len(chapters),
            )
    if rebuild_targets or deleted_chapter_ids:
        total = state_store.replace_chunks_for_chapters(
            workspace_id,
            [chapter["id"] for chapter, _signature in rebuild_targets],
            chunk_rows,
            index_entries,
            deleted_chapter_ids=deleted_chapter_ids,
        )
        _ = total
    return {
        "indexed_textbooks": _count_textbooks(workspace_id),
        "chunk_count": state_store.count_chunks(workspace_id),
        "reused_chapters": reused_entries,
        "rebuilt_chapters": len(rebuild_targets),
    }


def query(question: str, top_k: int = 5, workspace_id: str = "global") -> RagQueryResponse:
    started = time.perf_counter()
    rows = state_store.list_chunks_with_context(workspace_id)
    if not rows:
        return RagQueryResponse(answer="当前知识库中未找到相关信息", citations=[], source_chunks=[], elapsed_ms=0, token_estimate=estimate_tokens([question]))

    chunks = rows
    vector_scores = _vector_scores(question, chunks)
    bm25_scores = _bm25_scores(question, chunks)
    ranked = []
    for chunk in chunks:
        vector_score = vector_scores.get(chunk["id"], 0.0)
        keyword_score = bm25_scores.get(chunk["id"], 0.0)
        if embedding_service.using_fallback and keyword_score <= 0:
            continue
        score = 0.68 * vector_score + 0.32 * keyword_score
        if score >= 0.12:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    top = [(score, chunk) for score, chunk in ranked[:top_k] if score > 0]
    if not top or not _has_specific_query_overlap(question, top):
        return RagQueryResponse(answer="当前知识库中未找到相关信息", citations=[], source_chunks=[], elapsed_ms=int((time.perf_counter() - started) * 1000), token_estimate=estimate_tokens([question]))

    answer_result = _answer_with_context(question, top, workspace_id=workspace_id)
    citations = [
        Citation(
            textbook=chunk["textbook"],
            chapter=chunk["chapter"],
            page=chunk["page_start"],
            relevance_score=round(float(score), 4),
            chunk_id=chunk["id"],
            text=chunk["text"],
        )
        for score, chunk in top
    ]
    elapsed = int((time.perf_counter() - started) * 1000) + answer_result.get("elapsed_ms", 0)
    token_estimate = estimate_tokens([question, *(chunk["text"] for _, chunk in top), answer_result["answer"]])
    state_store.insert_metric(workspace_id, "rag_elapsed_ms", elapsed, {"question": question})
    state_store.insert_metric(workspace_id, "rag_token_estimate", token_estimate, {"question": question})
    return RagQueryResponse(
        answer=answer_result["answer"],
        citations=citations,
        source_chunks=[chunk["text"] for _, chunk in top],
        elapsed_ms=elapsed,
        token_estimate=token_estimate,
    )


def status(workspace_id: str = "global") -> dict:
    return {"indexed_textbooks": _count_textbooks(workspace_id), "chunk_count": state_store.count_chunks(workspace_id)}


def _vector_scores(question: str, chunks: list[dict]) -> dict[str, float]:
    query_vector = embedding_service.embed([question])[0]
    scores: dict[str, float] = {}
    for chunk in chunks:
        try:
            vector = json.loads(chunk["embedding"]) if chunk["embedding"] else embedding_service.embed([chunk["text"]])[0]
        except json.JSONDecodeError:
            vector = embedding_service.embed([chunk["text"]])[0]
        scores[chunk["id"]] = _cosine(query_vector, vector)
    if scores:
        min_score = min(scores.values())
        max_score = max(scores.values())
        spread = max(max_score - min_score, 1e-9)
        scores = {key: (value - min_score) / spread for key, value in scores.items()}
    return scores


def _bm25_scores(question: str, chunks: list[dict]) -> dict[str, float]:
    query_terms = tokenize(question)
    if not query_terms:
        return {chunk["id"]: 0.0 for chunk in chunks}
    documents = [tokenize(chunk["text"]) for chunk in chunks]
    doc_freq = Counter(term for document in documents for term in set(document))
    scores = {}
    for chunk, document in zip(chunks, documents):
        term_counts = Counter(document)
        score = 0.0
        for term in query_terms:
            if term not in term_counts:
                continue
            idf = max(0.1, len(documents) / (1 + doc_freq[term]))
            score += term_counts[term] * idf
        scores[chunk["id"]] = score
    max_score = max(scores.values()) if scores else 0
    if max_score > 0:
        scores = {key: value / max_score for key, value in scores.items()}
    return scores


def _specific_query_terms(question: str) -> set[str]:
    return {
        term
        for term in tokenize(question)
        if len(term) >= 2 and term not in GENERIC_QUERY_TERMS
    }


def _has_specific_query_overlap(question: str, top: list[tuple[float, dict]]) -> bool:
    terms = _specific_query_terms(question)
    if not terms:
        return False
    for _, chunk in top:
        chunk_terms = set(tokenize(chunk["text"]))
        if len(terms & chunk_terms) >= 2:
            return True
    return False


def _answer_with_context(question: str, top: list[tuple[float, dict]], workspace_id: str = "global") -> dict:
    context = "\n\n".join(
        f"[{index}] {chunk['textbook']} / {chunk['chapter']} / 第 {chunk['page_start']} 页\n{chunk['text']}"
        for index, (_, chunk) in enumerate(top, start=1)
    )
    result = llm_client.complete_text(
        "你是严谨的教材 RAG 问答 Agent。只基于上下文回答，必须引用来源；找不到就回答当前知识库中未找到相关信息。",
        f"问题: {question}\n\n上下文:\n{context}",
        workspace_id=workspace_id,
    )
    if result.get("data"):
        return {"answer": result["data"], "elapsed_ms": result.elapsed_ms}
    first = top[0][1]
    answer = f"根据《{first['textbook']}》{first['chapter']}第 {first['page_start']} 页，{first['text'][:220]}..."
    answer += f"\n\n引用来源：[《{first['textbook']}》, {first['chapter']}, 第 {first['page_start']} 页]"
    return {"answer": answer, "elapsed_ms": 0}


def _count_textbooks(workspace_id: str = "global") -> int:
    return state_store.count_completed_textbooks(workspace_id)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
