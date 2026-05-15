from __future__ import annotations

from pathlib import Path

from backend.app.agents.report import ReportAgent
from backend.app.config import settings
from backend.app.db import connect, init_db
from backend.app.schemas import KnowledgeEdge, KnowledgeNode
from backend.app.services.embedding import embedding_service
from backend.app.services import graph as graph_service
from backend.app.services.graph import build_graph
from backend.app.services.integration import run_integration
from backend.app.services.parser import parse_textbook
from backend.app.services.rag import build_index, query
from backend.app.services.textbooks import import_textbook_file, list_textbooks
from backend.app.utils.ids import new_id


def test_services_end_to_end(tmp_path: Path) -> None:
    original_database_url = settings.database_url
    original_llm_base_url = settings.llm_base_url
    original_llm_api_key = settings.llm_api_key
    object.__setattr__(settings, "database_url", f"sqlite:///{tmp_path / 'app.db'}")
    object.__setattr__(settings, "llm_base_url", "")
    object.__setattr__(settings, "llm_api_key", "")
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
        assert graph["metrics"]["fallback_chapters"] == graph["metrics"]["processed_chapters"]
        assert graph["metrics"]["llm_chapters"] == 0
        assert graph["metrics"]["llm_configured"] is False
        assert graph["nodes"][0]["chapter_title"]
        assert graph["nodes"][0]["chapter_position"] >= 1
        assert graph["nodes"][0]["page_start"] >= 1
        integrated = run_integration()
        assert integrated["decisions"]
        assert integrated["nodes"][0]["chapter_title"]
        assert integrated["nodes"][0]["chapter_position"] >= 1
        report_data = ReportAgent().collect_data()
        assert report_data["integrated_chars"] == integrated["stats"]["integrated_chars"]
        status = build_index()
        assert status["chunk_count"] > 0
        answer = query("快速排序采用什么思想？")
        assert answer.citations
        assert "当前知识库中未找到相关信息" not in answer.answer
    finally:
        object.__setattr__(settings, "database_url", original_database_url)
        object.__setattr__(settings, "llm_base_url", original_llm_base_url)
        object.__setattr__(settings, "llm_api_key", original_llm_api_key)


def test_build_graph_limits_processed_chapters_and_reports_truncation(tmp_path: Path, monkeypatch) -> None:
    original_database_url = settings.database_url
    object.__setattr__(settings, "database_url", f"sqlite:///{tmp_path / 'app.db'}")
    object.__setattr__(settings, "graph_max_chapters", 2)

    class FakeExtractionAgent:
        def extract(self, chapter: dict, textbook_id: str, workspace_id: str = "global"):
            node = KnowledgeNode(
                id=f"node_{chapter['position']}",
                textbook_id=textbook_id,
                chapter_id=chapter["id"],
                name=f"概念{chapter['position']}",
                definition="章节核心概念",
                category="核心概念",
                page=chapter["page_start"],
                source_excerpt=chapter["content"],
            )
            edge = KnowledgeEdge(
                id=f"edge_{chapter['position']}",
                textbook_id=textbook_id,
                source=node.id,
                target=node.id,
                relation_type="parallel",
                description="自测关系",
            )
            return [node], [edge], {"elapsed_ms": 3, "token_estimate": 5}

    monkeypatch.setattr(graph_service, "KnowledgeExtractionAgent", FakeExtractionAgent)
    try:
        init_db()
        textbook_id = new_id("book")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks
                (id, filename, title, format, size_bytes, total_pages, total_chars, status, error, created_at)
                VALUES (?, 'sample.md', 'sample', 'md', 10, 1, 300, 'completed', NULL, '2026-05-14T00:00:00Z')
                """,
                (textbook_id,),
            )
            for position in range(1, 4):
                conn.execute(
                    """
                    INSERT INTO chapters (id, textbook_id, title, page_start, page_end, content, char_count, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"chapter_{position}",
                        textbook_id,
                        f"第 {position} 章",
                        position,
                        position,
                        f"第 {position} 章内容",
                        100,
                        position,
                    ),
                )

        graph = build_graph(textbook_id, max_chapters=1)

        assert graph["metrics"]["processed_chapters"] == 1
        assert graph["metrics"]["total_chapters"] == 3
        assert graph["metrics"]["truncated"] is True
        assert graph["metrics"]["fallback_chapters"] == 0
        assert graph["metrics"]["llm_chapters"] == 1
        assert graph["metrics"]["llm_configured"] is False
        assert len(graph["nodes"]) == 1
        assert graph["nodes"][0]["chapter_title"] == "第 1 章"
        assert graph["nodes"][0]["chapter_position"] == 1
        assert graph["nodes"][0]["page_start"] == 1
        assert graph["nodes"][0]["page_end"] == 1
    finally:
        object.__setattr__(settings, "database_url", original_database_url)
        object.__setattr__(settings, "graph_max_chapters", 30)


def test_import_textbook_file_preserves_name_and_reports_graph_counts(tmp_path: Path) -> None:
    original_database_url = settings.database_url
    original_upload_dir = settings.upload_dir
    object.__setattr__(settings, "database_url", f"sqlite:///{tmp_path / 'app.db'}")
    object.__setattr__(settings, "upload_dir", tmp_path / "uploads")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        init_db()
        source = tmp_path / "样例教材.md"
        source.write_text("# 第 1 章 绪论\n知识图谱用于表示概念关系。", encoding="utf-8")

        textbook = import_textbook_file(source)
        chapter = textbook["chapters"][0]

        assert textbook["filename"] == "样例教材.md"
        assert textbook["title"] == "样例教材"
        assert textbook["status"] == "completed"

        with connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_nodes
                (id, textbook_id, chapter_id, name, definition, category, page, source_excerpt, frequency, metadata)
                VALUES ('node_count_test', ?, ?, '知识图谱', '定义', '核心概念', 1, '原文', 1, '{}')
                """,
                (textbook["id"], chapter["id"]),
            )
            conn.execute(
                """
                INSERT INTO knowledge_edges (id, textbook_id, source, target, relation_type, description)
                VALUES ('edge_count_test', ?, 'node_count_test', 'node_count_test', 'parallel', '测试关系')
                """,
                (textbook["id"],),
            )

        listed = list_textbooks()

        assert listed[0]["graph_node_count"] == 1
        assert listed[0]["graph_edge_count"] == 1
    finally:
        object.__setattr__(settings, "database_url", original_database_url)
        object.__setattr__(settings, "upload_dir", original_upload_dir)
