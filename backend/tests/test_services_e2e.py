from __future__ import annotations

from pathlib import Path

from backend.app.config import settings
from backend.app.db import connect, init_db
from backend.app.services.embedding import embedding_service
from backend.app.services.graph import build_graph
from backend.app.services.integration import run_integration
from backend.app.services.parser import parse_textbook
from backend.app.services.rag import build_index, query
from backend.app.utils.ids import new_id


def test_services_end_to_end(tmp_path: Path) -> None:
    original_database_url = settings.database_url
    object.__setattr__(settings, "database_url", f"sqlite:///{tmp_path / 'app.db'}")
    embedding_service._model_failed = True
    embedding_service._model = None
    try:
        init_db()
        textbook_id = new_id("book")
        path = tmp_path / "算法.md"
        path.write_text(
            "第 1 章 排序算法\n排序算法用于将数据按关键字排列。快速排序采用分治思想。归并排序也采用分治思想。\n"
            "第 2 章 图结构\n图由顶点和边组成。最短路径算法用于寻找顶点之间的最短距离。",
            encoding="utf-8",
        )
        parsed = parse_textbook(path, path.name)
        with connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO textbooks
                (id, filename, title, format, size_bytes, total_pages, total_chars, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', NULL, '2026-05-14T00:00:00Z')
                """,
                (textbook_id, path.name, parsed["title"], parsed["format"], path.stat().st_size, parsed["total_pages"], parsed["total_chars"]),
            )
            conn.execute("DELETE FROM chapters WHERE textbook_id = ?", (textbook_id,))
            for position, chapter in enumerate(parsed["chapters"], start=1):
                conn.execute(
                    """
                    INSERT INTO chapters (id, textbook_id, title, page_start, page_end, content, char_count, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("ch"),
                        textbook_id,
                        chapter["title"],
                        chapter["page_start"],
                        chapter["page_end"],
                        chapter["content"],
                        chapter["char_count"],
                        position,
                    ),
                )

        graph = build_graph(textbook_id)
        assert graph["nodes"]
        integrated = run_integration()
        assert integrated["decisions"]
        status = build_index()
        assert status["chunk_count"] > 0
        answer = query("快速排序采用什么思想？")
        assert answer.citations
        assert "当前知识库中未找到相关信息" not in answer.answer
    finally:
        object.__setattr__(settings, "database_url", original_database_url)
