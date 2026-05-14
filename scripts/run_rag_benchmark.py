from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db import init_db
from backend.app.services.embedding import embedding_service
from backend.app.services import rag


QUESTIONS = [
    {"question": "快速排序采用什么思想？", "expected_source_hint": "排序算法"},
    {"question": "归并排序采用什么思想？", "expected_source_hint": "排序算法"},
    {"question": "图由什么组成？", "expected_source_hint": "图结构"},
    {"question": "最短路径算法用于什么？", "expected_source_hint": "图结构"},
    {"question": "免疫系统如何工作？", "expected_source_hint": ""},
]


def main() -> None:
    init_db()
    embedding_service._model_failed = True
    embedding_service._model = None
    output = []
    started = time.perf_counter()
    status = rag.status()
    for item in QUESTIONS:
        response = rag.query(item["question"], top_k=5)
        output.append(
            {
                "question": item["question"],
                "answer": response.answer,
                "citation_count": len(response.citations),
                "elapsed_ms": response.elapsed_ms,
                "token_estimate": response.token_estimate,
                "has_citation": bool(response.citations),
            }
        )
    summary = {
        "status": status,
        "question_count": len(QUESTIONS),
        "total_elapsed_ms": int((time.perf_counter() - started) * 1000),
        "citation_accuracy_proxy": sum(1 for row in output if row["has_citation"]) / len(output),
        "results": output,
    }
    path = Path("data/generated/rag-benchmark.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
