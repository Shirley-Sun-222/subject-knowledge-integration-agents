from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.agents.report import ReportAgent
from backend.app.config import settings
from backend.app.db import connect, init_db
from backend.app.services import rag
from backend.app.services.graph import build_graph
from backend.app.services.integration import run_integration
from backend.app.services.textbooks import import_textbook_file


SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt", ".docx"}


def sample_files(sample_dir: Path, limit: int | None) -> list[Path]:
    files = sorted(path for path in sample_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)
    return files[:limit] if limit else files


def existing_textbooks_by_filename() -> dict[str, dict[str, Any]]:
    with connect() as conn:
        return {row["filename"]: dict(row) for row in conn.execute("SELECT * FROM textbooks")}


def reset_sample_rows(filenames: list[str]) -> int:
    if not filenames:
        return 0
    placeholders = ",".join("?" for _ in filenames)
    with connect() as conn:
        ids = [row["id"] for row in conn.execute(f"SELECT id FROM textbooks WHERE filename IN ({placeholders})", filenames)]
        if not ids:
            return 0
        id_placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM chunks WHERE textbook_id IN ({id_placeholders})", ids)
        conn.execute(f"DELETE FROM knowledge_edges WHERE textbook_id IN ({id_placeholders})", ids)
        conn.execute(f"DELETE FROM knowledge_nodes WHERE textbook_id IN ({id_placeholders})", ids)
        conn.execute(f"DELETE FROM chapters WHERE textbook_id IN ({id_placeholders})", ids)
        conn.execute(f"DELETE FROM textbooks WHERE id IN ({id_placeholders})", ids)
        conn.execute("DELETE FROM integration_decisions")
        return len(ids)


def graph_ready_textbook_ids(filenames: list[str]) -> list[str]:
    if not filenames:
        return []
    placeholders = ",".join("?" for _ in filenames)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT id FROM textbooks WHERE filename IN ({placeholders}) AND status = 'completed' ORDER BY created_at",
            filenames,
        )
        return [row["id"] for row in rows]


def configure_runtime(args: argparse.Namespace) -> None:
    if args.ocr_max_pages is not None:
        object.__setattr__(settings, "ocr_max_pages", args.ocr_max_pages)
    if args.graph_max_chapters is not None:
        object.__setattr__(settings, "graph_max_chapters", args.graph_max_chapters)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import ignored textbook samples into the local app database.")
    parser.add_argument("--sample-dir", default="book_samples", help="Directory containing local textbook samples.")
    parser.add_argument("--limit", type=int, default=None, help="Import at most N files.")
    parser.add_argument("--reset-samples", action="store_true", help="Delete existing rows whose filename matches sample files before importing.")
    parser.add_argument("--build-graphs", action="store_true", help="Build single-textbook graphs after import.")
    parser.add_argument("--integrate", action="store_true", help="Run cross-textbook integration after graph build.")
    parser.add_argument("--index-rag", action="store_true", help="Build the RAG index after import.")
    parser.add_argument("--report", action="store_true", help="Generate the Markdown integration report after import/integration.")
    parser.add_argument("--ocr-max-pages", type=int, default=None, help="Override OCR_MAX_PAGES for this run.")
    parser.add_argument("--graph-max-chapters", type=int, default=None, help="Override GRAPH_MAX_CHAPTERS for this run.")
    args = parser.parse_args()

    configure_runtime(args)
    init_db()
    sample_dir = (ROOT / args.sample_dir).resolve()
    if not sample_dir.exists() or not sample_dir.is_dir():
        raise SystemExit(f"Sample directory not found: {sample_dir}")

    files = sample_files(sample_dir, args.limit)
    filenames = [path.name for path in files]
    deleted = reset_sample_rows(filenames) if args.reset_samples else 0
    existing = existing_textbooks_by_filename()
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for path in files:
        if path.name in existing:
            skipped.append({"filename": path.name, "id": existing[path.name]["id"], "status": existing[path.name]["status"]})
            continue
        textbook = import_textbook_file(path, original_filename=path.name)
        imported.append(
            {
                "id": textbook["id"],
                "filename": textbook["filename"],
                "title": textbook["title"],
                "status": textbook["status"],
                "chapters": len(textbook.get("chapters", [])),
                "total_chars": textbook.get("total_chars", 0),
                "error": textbook.get("error"),
            }
        )

    graph_results = []
    if args.build_graphs:
        for textbook_id in graph_ready_textbook_ids(filenames):
            graph = build_graph(textbook_id)
            graph_results.append(
                {
                    "textbook_id": textbook_id,
                    "nodes": len(graph["nodes"]),
                    "edges": len(graph["edges"]),
                    "metrics": graph.get("metrics", {}),
                }
            )

    integration_result = run_integration() if args.integrate else None
    rag_status = rag.build_index() if args.index_rag else None
    if args.report:
        ReportAgent().generate_markdown()
        report_path = str(ROOT / "report" / "整合报告.md")
    else:
        report_path = None

    print(
        json.dumps(
            {
                "sample_dir": str(sample_dir),
                "file_count": len(files),
                "deleted_existing": deleted,
                "imported": imported,
                "skipped": skipped,
                "graphs": graph_results,
                "integration": integration_result["stats"] if integration_result else None,
                "rag": rag_status,
                "report": report_path,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
