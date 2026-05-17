from __future__ import annotations

import asyncio
import io
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi import Response
from starlette.requests import Request

from backend.app.agents.report import ReportAgent
from backend.app.config import settings
from backend.app.db import connect, init_db
from backend.app import main
from backend.app.runtime import store as store_module
from backend.app.runtime.store import state_store
from backend.app.runtime.tasks import TaskContext, task_runner
from backend.app.schemas import KnowledgeNode
from backend.app.services import graph as graph_service
from backend.app.services import rag as rag_service
from backend.app.services.embedding import embedding_service
from backend.app.services.textbooks import import_textbook_file
from backend.app.utils.ids import new_id

WORKSPACE_ID = "ws_test"


def _set_runtime_paths(tmp_path: Path) -> dict[str, object]:
    originals = {
        "database_url": settings.database_url,
        "upload_dir": settings.upload_dir,
        "generated_dir": settings.generated_dir,
        "index_dir": settings.index_dir,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
    }
    object.__setattr__(settings, "database_url", f"sqlite:///{tmp_path / 'app.db'}")
    object.__setattr__(settings, "upload_dir", tmp_path / "uploads")
    object.__setattr__(settings, "generated_dir", tmp_path / "generated")
    object.__setattr__(settings, "index_dir", tmp_path / "indexes")
    object.__setattr__(settings, "llm_base_url", "")
    object.__setattr__(settings, "llm_api_key", "")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    embedding_service._model_failed = True
    embedding_service._model = None
    return originals


def _restore_runtime_paths(originals: dict[str, object]) -> None:
    for key, value in originals.items():
        object.__setattr__(settings, key, value)


def _request(workspace_id: str = WORKSPACE_ID) -> Request:
    headers = [(b"cookie", f"session_workspace_id={workspace_id}".encode("utf-8"))]
    return Request({"type": "http", "headers": headers, "query_string": b"", "method": "GET", "path": "/"})


def _response() -> Response:
    return Response()


def test_task_store_dedupes_active_tasks(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        state_store.ensure_workspace(WORKSPACE_ID)
        first, created = state_store.create_or_get_active_task(WORKSPACE_ID, "build_graph", "textbook", "book-1")
        second, second_created = state_store.create_or_get_active_task(WORKSPACE_ID, "build_graph", "textbook", "book-1")

        assert created is True
        assert second_created is False
        assert first["id"] == second["id"]

        state_store.mark_task_running(WORKSPACE_ID, first["id"], phase="extracting_graph", progress_total=3)
        state_store.update_task_progress(WORKSPACE_ID, first["id"], progress_current=2, progress_total=3, truncated=True)
        state_store.succeed_task(WORKSPACE_ID, first["id"], result_ref="book-1", truncated=True)

        stored = state_store.get_task(WORKSPACE_ID, first["id"])
        assert stored["status"] == "succeeded"
        assert stored["progress_current"] == 2
        assert stored["progress_total"] == 3
        assert stored["truncated"] is True
        assert stored["result_ref"] == "book-1"
    finally:
        _restore_runtime_paths(originals)


def test_upload_api_enqueues_parse_task_and_completes(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        main.startup()
        upload = UploadFile(file=io.BytesIO("# 第 1 章 绪论\n知识图谱用于表示概念关系。".encode("utf-8")), filename="样例教材.md")
        payload = asyncio.run(main.upload_textbooks(_request(), _response(), [upload]))

        assert len(payload["uploads"]) == 1
        assert payload["uploads"][0]["task"]["task_type"] == "preview_parse_textbook"
        task_id = payload["uploads"][0]["task"]["id"]
        textbook_id = payload["uploads"][0]["textbook"]["id"]

        task = task_runner.wait_for(WORKSPACE_ID, task_id)
        assert task["status"] == "succeeded"
        assert task["result_ref"] == textbook_id

        task_response = main.get_task(task_id, _request(), _response())
        assert task_response["task"]["status"] == "succeeded"

        textbooks = main.list_textbooks(_request(), _response())["textbooks"]
        uploaded = next(item for item in textbooks if item["id"] == textbook_id)
        assert uploaded["status"] == "completed"
        assert uploaded["preview_ready"] is True
        assert uploaded["full_ready"] is True
        assert uploaded["parse_scope"] == "full"
        assert uploaded["chapter_count"] >= 1
    finally:
        _restore_runtime_paths(originals)


def test_workspace_isolation_keeps_textbooks_separate(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        main.startup()
        upload = UploadFile(file=io.BytesIO("# 第 1 章 绪论\n知识图谱用于表示概念关系。".encode("utf-8")), filename="样例教材.md")
        payload = asyncio.run(main.upload_textbooks(_request("ws_a"), _response(), [upload]))
        task_runner.wait_for("ws_a", payload["uploads"][0]["task"]["id"])

        own = main.list_textbooks(_request("ws_a"), _response())["textbooks"]
        other = main.list_textbooks(_request("ws_b"), _response())["textbooks"]

        assert len(own) == 1
        assert other == []
    finally:
        _restore_runtime_paths(originals)


def test_delete_textbook_removes_records_and_upload(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        main.startup()
        upload = UploadFile(file=io.BytesIO("# 第 1 章 绪论\n知识图谱用于表示概念关系。".encode("utf-8")), filename="样例教材.md")
        payload = asyncio.run(main.upload_textbooks(_request(), _response(), [upload]))
        textbook_id = payload["uploads"][0]["textbook"]["id"]
        task_runner.wait_for(WORKSPACE_ID, payload["uploads"][0]["task"]["id"])

        textbook = state_store.get_textbook_record(WORKSPACE_ID, textbook_id)
        stored_path = settings.upload_dir / WORKSPACE_ID / f"{textbook_id}.{textbook['format']}"
        assert stored_path.exists()

        response = main.delete_textbook(textbook_id, _request(), _response())
        assert response["deleted"] == textbook_id
        assert main.list_textbooks(_request(), _response())["textbooks"] == []
        assert not stored_path.exists()
    finally:
        _restore_runtime_paths(originals)


def test_pdf_upload_preview_parse_enqueues_full_parse_task(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    originals = _set_runtime_paths(tmp_path)
    try:
        main.startup()
        pdf_path = tmp_path / "医学教材.pdf"
        document = fitz.open()
        toc = []
        page_number = 1
        for chapter in range(1, 5):
            toc.append([1, f"第 {chapter} 章 教学章{chapter}", page_number])
            for chapter_page in range(1, 4):
                page = document.new_page()
                page.insert_text((72, 72), f"第 {chapter} 章 第 {chapter_page} 页\n生理学教学内容 {chapter}-{chapter_page}。")
                page_number += 1
        document.set_toc(toc)
        document.save(pdf_path)
        document.close()

        upload = UploadFile(file=io.BytesIO(pdf_path.read_bytes()), filename=pdf_path.name)
        payload = asyncio.run(main.upload_textbooks(_request(), _response(), [upload]))
        preview_task_id = payload["uploads"][0]["task"]["id"]
        textbook_id = payload["uploads"][0]["textbook"]["id"]

        preview_task = task_runner.wait_for(WORKSPACE_ID, preview_task_id)
        assert preview_task["status"] == "succeeded"

        textbooks = main.list_textbooks(_request(), _response())["textbooks"]
        uploaded = next(item for item in textbooks if item["id"] == textbook_id)
        assert uploaded["preview_ready"] is True
        assert uploaded["parse_stage"] in {"preview", "full"}
        assert uploaded["chapter_count"] <= 3 or uploaded["full_ready"] is True

        full_tasks = main.list_tasks(_request(), _response(), task_type="full_parse_textbook")["tasks"]
        assert any(task["resource_id"] == textbook_id for task in full_tasks)
        for task in full_tasks:
            if task["status"] in {"queued", "running"}:
                task_runner.wait_for(WORKSPACE_ID, task["id"])
    finally:
        _restore_runtime_paths(originals)


def test_rag_index_requires_full_ready_textbooks(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        state_store.ensure_workspace(WORKSPACE_ID)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks
                (id, workspace_id, filename, title, format, size_bytes, total_pages, total_chars, status, parse_stage, preview_ready, full_ready, parse_scope, created_at)
                VALUES ('book-preview', ?, 'preview.pdf', 'preview', 'pdf', 10, 3, 300, 'preview_ready', 'preview', 1, 0, 'preview', '2026-05-18T00:00:00Z')
                """,
                (WORKSPACE_ID,),
            )

        try:
            main.build_rag_index(_request(), _response())
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
        else:
            raise AssertionError("RAG indexing should require full-ready textbooks")
    finally:
        _restore_runtime_paths(originals)


def test_full_graph_api_requires_full_ready_textbook(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        state_store.ensure_workspace(WORKSPACE_ID)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks
                (id, workspace_id, filename, title, format, size_bytes, total_pages, total_chars, status, parse_stage, preview_ready, full_ready, parse_scope, created_at)
                VALUES ('book-preview', ?, 'preview.pdf', 'preview', 'pdf', 10, 3, 300, 'preview_ready', 'preview', 1, 0, 'preview', '2026-05-18T00:00:00Z')
                """,
                (WORKSPACE_ID,),
            )

        try:
            main.build_graph({"textbook_id": "book-preview", "mode": "full"}, _request(), _response())
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
        else:
            raise AssertionError("Full graph construction should require full-ready textbooks")
    finally:
        _restore_runtime_paths(originals)


def test_full_parse_preserves_preview_graph_as_stale(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        state_store.ensure_workspace(WORKSPACE_ID)
        textbook_id = new_id("book")
        chapter_id = new_id("ch")
        node_id = new_id("node")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks
                (id, workspace_id, filename, title, format, size_bytes, total_pages, total_chars, status, parse_stage, preview_ready, full_ready, parse_scope, graph_scope, created_at)
                VALUES (?, ?, 'preview.pdf', 'preview', 'pdf', 10, 3, 100, 'preview_ready', 'preview', 1, 0, 'preview', 'preview', '2026-05-18T00:00:00Z')
                """,
                (textbook_id, WORKSPACE_ID),
            )
            conn.execute(
                """
                INSERT INTO chapters (id, workspace_id, textbook_id, title, page_start, page_end, content, char_count, position)
                VALUES (?, ?, ?, '第 1 章', 1, 3, '预览章节内容', 30, 1)
                """,
                (chapter_id, WORKSPACE_ID, textbook_id),
            )
            conn.execute(
                """
                INSERT INTO knowledge_nodes
                (id, workspace_id, textbook_id, chapter_id, name, definition, category, page, source_excerpt, frequency, metadata)
                VALUES (?, ?, ?, ?, '预览概念', '定义', '核心概念', 1, '出处', 1, '{}')
                """,
                (node_id, WORKSPACE_ID, textbook_id, chapter_id),
            )

        state_store.complete_textbook_parse(
            WORKSPACE_ID,
            textbook_id,
            {
                "title": "preview",
                "format": "pdf",
                "total_pages": 6,
                "total_chars": 300,
                "chapters": [
                    {
                        "title": "第 1 章",
                        "page_start": 1,
                        "page_end": 6,
                        "content": "全量章节内容" * 20,
                        "char_count": 120,
                    }
                ],
            },
        )

        graph = state_store.get_graph(WORKSPACE_ID, textbook_id)
        textbook = state_store.get_textbook_record(WORKSPACE_ID, textbook_id)
        assert graph["nodes"]
        assert graph["nodes"][0]["metadata"]["stale_after_full_parse"] is True
        assert graph["textbook"]["graph_scope"] == "preview"
        assert graph["textbook"]["graph_stale_after_full_parse"] is True
        assert textbook["full_ready"] is True
        assert textbook["graph_stale_after_full_parse"] is True
    finally:
        _restore_runtime_paths(originals)


def test_preview_graph_race_after_full_parse_remaps_stale_nodes(tmp_path: Path, monkeypatch) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_workers = settings.graph_extract_workers
    try:
        object.__setattr__(settings, "graph_extract_workers", 1)
        init_db()
        state_store.ensure_workspace(WORKSPACE_ID)
        textbook_id = new_id("book")
        preview_chapter_id = new_id("ch")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks
                (id, workspace_id, filename, title, format, size_bytes, total_pages, total_chars, status, parse_stage, preview_ready, full_ready, parse_scope, graph_scope, created_at)
                VALUES (?, ?, 'preview.pdf', 'preview', 'pdf', 10, 3, 100, 'preview_ready', 'preview', 1, 0, 'preview', 'preview', '2026-05-18T00:00:00Z')
                """,
                (textbook_id, WORKSPACE_ID),
            )
            conn.execute(
                """
                INSERT INTO chapters (id, workspace_id, textbook_id, title, page_start, page_end, content, char_count, position)
                VALUES (?, ?, ?, '第 1 章', 1, 3, '预览章节内容预览章节内容预览章节内容', 60, 1)
                """,
                (preview_chapter_id, WORKSPACE_ID, textbook_id),
            )

        class RaceExtractionAgent:
            def extract_fast(self, chapter: dict, textbook_id: str):
                state_store.complete_textbook_parse(
                    WORKSPACE_ID,
                    textbook_id,
                    {
                        "title": "preview",
                        "format": "pdf",
                        "total_pages": 6,
                        "total_chars": 300,
                        "chapters": [
                            {
                                "title": "第 1 章",
                                "page_start": 1,
                                "page_end": 6,
                                "content": "全量章节内容" * 20,
                                "char_count": 120,
                            }
                        ],
                    },
                )
                return [
                    KnowledgeNode(
                        id=new_id("node"),
                        textbook_id=textbook_id,
                        chapter_id=chapter["id"],
                        name="预览概念",
                        definition="定义",
                        category="核心概念",
                        page=1,
                        source_excerpt="出处",
                    )
                ], []

        monkeypatch.setattr(graph_service, "KnowledgeExtractionAgent", RaceExtractionAgent)

        graph = graph_service.build_graph(textbook_id, max_chapters=1, workspace_id=WORKSPACE_ID)

        assert graph["nodes"]
        assert graph["nodes"][0]["chapter_id"] != preview_chapter_id
        assert graph["nodes"][0]["metadata"]["stale_after_full_parse"] is True
        assert graph["textbook"]["graph_scope"] == "preview"
        assert graph["textbook"]["graph_stale_after_full_parse"] is True
        assert graph["metrics"]["stale_after_full_parse"] is True
    finally:
        object.__setattr__(settings, "graph_extract_workers", original_workers)
        _restore_runtime_paths(originals)


def test_session_llm_config_overrides_global_llm(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_global_base = settings.llm_base_url
    original_global_key = settings.llm_api_key
    original_global_model = settings.llm_model
    try:
        object.__setattr__(settings, "llm_base_url", "https://global.example.test/v1")
        object.__setattr__(settings, "llm_api_key", "global-key")
        object.__setattr__(settings, "llm_model", "global-model")
        main.startup()

        none_status = main.session_llm_config_status(_request("ws_model"), _response())["status"]
        assert none_status["source"] == "global"

        from backend.app.schemas import SessionLlmConfigRequest

        main.set_session_llm_config(
            SessionLlmConfigRequest(base_url="https://session.example.test/v1", api_key="session-key", model="session-model"),
            _request("ws_model"),
            _response(),
        )
        session_status = main.session_llm_config_status(_request("ws_model"), _response())["status"]
        assert session_status["source"] == "session"
        assert session_status["model"] == "session-model"

        main.delete_session_llm_config(_request("ws_model"), _response())
        cleared_status = main.session_llm_config_status(_request("ws_model"), _response())["status"]
        assert cleared_status["source"] == "global"
    finally:
        object.__setattr__(settings, "llm_base_url", original_global_base)
        object.__setattr__(settings, "llm_api_key", original_global_key)
        object.__setattr__(settings, "llm_model", original_global_model)
        _restore_runtime_paths(originals)


def test_startup_recovers_from_malformed_sqlite(monkeypatch) -> None:
    calls = {"count": 0, "reset": 0, "backup": 0}
    original = main._startup_runtime
    try:
        def flaky_startup():
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.DatabaseError("database disk image is malformed")

        monkeypatch.setattr(main, "_startup_runtime", flaky_startup)
        monkeypatch.setattr(main, "backup_corrupt_database", lambda: calls.__setitem__("backup", calls["backup"] + 1) or Path("/tmp/fake.bak"))
        monkeypatch.setattr(main.runtime_files, "reset_runtime_storage", lambda: calls.__setitem__("reset", calls["reset"] + 1))

        main.startup()

        assert calls["count"] == 2
        assert calls["backup"] == 1
        assert calls["reset"] == 1
    finally:
        monkeypatch.setattr(main, "_startup_runtime", original)


def test_workspace_activity_writes_are_throttled(tmp_path: Path, monkeypatch) -> None:
    workspace_id = "ws_touch_test"
    originals = _set_runtime_paths(tmp_path)
    original_interval = settings.workspace_touch_interval_seconds
    original_clock = state_store._clock
    timestamp = {"value": 0}
    tick = {"value": 0.0}
    try:
        object.__setattr__(settings, "workspace_touch_interval_seconds", 60)
        monkeypatch.setattr(state_store, "_clock", lambda: tick["value"])

        def fake_utc_now() -> str:
            timestamp["value"] += 1
            return f"2026-05-15T00:00:{timestamp['value']:02d}+00:00"

        monkeypatch.setattr(store_module, "utc_now", fake_utc_now)
        init_db()
        state_store._forget_workspace_activity(workspace_id)

        state_store.ensure_workspace(workspace_id)
        first = state_store.get_workspace(workspace_id)

        state_store.ensure_workspace(workspace_id)
        second = state_store.get_workspace(workspace_id)

        tick["value"] = 61.0
        state_store.ensure_workspace(workspace_id)
        third = state_store.get_workspace(workspace_id)

        assert first["last_active_at"] == second["last_active_at"]
        assert third["last_active_at"] != second["last_active_at"]
    finally:
        state_store._forget_workspace_activity(workspace_id)
        object.__setattr__(settings, "workspace_touch_interval_seconds", original_interval)
        monkeypatch.setattr(state_store, "_clock", original_clock)
        _restore_runtime_paths(originals)


def test_task_context_throttles_high_frequency_progress_updates(monkeypatch) -> None:
    recorded: list[tuple[int | None, int | None, str | None]] = []
    original_interval = settings.task_progress_write_interval_seconds
    try:
        object.__setattr__(settings, "task_progress_write_interval_seconds", 60)
        monkeypatch.setattr(
            "backend.app.runtime.tasks.state_store.mark_task_running",
            lambda workspace_id, task_id, phase="running", progress_total=None: None,
        )
        monkeypatch.setattr(
            "backend.app.runtime.tasks.state_store.update_task_progress",
            lambda workspace_id, task_id, **kwargs: recorded.append(
                (kwargs.get("progress_current"), kwargs.get("progress_total"), kwargs.get("phase"))
            ),
        )

        context = TaskContext(workspace_id=WORKSPACE_ID, task_id="task-stress")
        context.start("parsing_textbook", progress_total=1)
        for current in range(1, 101):
            context.progress(phase="reading_pdf_pages", progress_current=current, progress_total=100)

        assert recorded[-1] == (100, 100, "reading_pdf_pages")
        assert len(recorded) < 35
    finally:
        object.__setattr__(settings, "task_progress_write_interval_seconds", original_interval)


def test_build_graph_api_reuses_active_task_for_same_textbook(tmp_path: Path, monkeypatch) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_build_graph = graph_service.build_graph
    try:
        init_db()
        source = tmp_path / "算法.md"
        source.write_text("第 1 章 排序\n快速排序采用分治思想。", encoding="utf-8")
        textbook = import_textbook_file(source, workspace_id=WORKSPACE_ID)

        def slow_build_graph(*args, **kwargs):
            time.sleep(0.2)
            return original_build_graph(*args, **kwargs)

        monkeypatch.setattr(graph_service, "build_graph", slow_build_graph)
        main.startup()
        first = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1}, _request(), _response())
        second = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1}, _request(), _response())

        first_task = first["task"]
        second_task = second["task"]
        assert first_task["id"] == second_task["id"]

        finished = task_runner.wait_for(WORKSPACE_ID, first_task["id"])
        assert finished["status"] == "succeeded"

        graph = main.get_graph(textbook["id"], _request(), _response())
        assert graph["nodes"]
        assert finished["truncated"] is False
    finally:
        monkeypatch.setattr(graph_service, "build_graph", original_build_graph)
        _restore_runtime_paths(originals)


def test_build_graph_returns_immediate_cache_hit_after_success(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        source = tmp_path / "算法.md"
        source.write_text("第 1 章 排序\n快速排序采用分治思想。", encoding="utf-8")
        textbook = import_textbook_file(source, workspace_id=WORKSPACE_ID)

        main.startup()
        first = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1}, _request(), _response())
        task_runner.wait_for(WORKSPACE_ID, first["task"]["id"])

        second = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1}, _request(), _response())
        detail = main.get_task(second["task"]["id"], _request(), _response())["task"]

        assert detail["status"] == "succeeded"
        assert detail["phase"] == "cache_hit"
        assert detail["result_ref"] == textbook["id"]
    finally:
        _restore_runtime_paths(originals)


def test_report_pdf_task_failure_is_recorded(tmp_path: Path, monkeypatch) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_generate_pdf = ReportAgent.generate_pdf
    try:
        async def failing_generate_pdf(self, workspace_id: str = "global"):
            raise RuntimeError("pdf engine unavailable")

        monkeypatch.setattr(ReportAgent, "generate_pdf", failing_generate_pdf)
        main.startup()
        response = main.integration_report_pdf_build(_request(), _response())
        task_id = response["task"]["id"]

        task = task_runner.wait_for(WORKSPACE_ID, task_id)
        assert task["status"] == "failed"
        assert "pdf engine unavailable" in (task["error_summary"] or "")
    finally:
        monkeypatch.setattr(ReportAgent, "generate_pdf", original_generate_pdf)
        _restore_runtime_paths(originals)


def test_rag_index_returns_immediate_cache_hit_when_fresh(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        source = tmp_path / "算法.md"
        source.write_text("第 1 章 排序\n快速排序采用分治思想。\n第 2 章 图\n图由顶点和边组成。", encoding="utf-8")
        import_textbook_file(source, workspace_id=WORKSPACE_ID)

        main.startup()
        first = main.build_rag_index(_request(), _response())
        task_runner.wait_for(WORKSPACE_ID, first["task"]["id"])

        second = main.build_rag_index(_request(), _response())
        detail = main.get_task(second["task"]["id"], _request(), _response())["task"]

        assert detail["status"] == "succeeded"
        assert detail["phase"] == "cache_hit"
        assert detail["result_ref"] == "rag-index:global"
    finally:
        _restore_runtime_paths(originals)


def test_rag_index_rebuilds_only_changed_chapters(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        source = tmp_path / "算法.md"
        source.write_text(
            "第 1 章 排序\n快速排序采用分治思想。\n第 2 章 图\n图由顶点和边组成。",
            encoding="utf-8",
        )
        textbook = import_textbook_file(source, workspace_id=WORKSPACE_ID)

        first = rag_service.build_index(workspace_id=WORKSPACE_ID)
        assert first["rebuilt_chapters"] == 2
        assert first["reused_chapters"] == 0

        chapters = state_store.get_chapters(WORKSPACE_ID, textbook["id"])
        target = chapters[0]
        with connect() as conn:
            conn.execute(
                "UPDATE chapters SET content = ?, char_count = ? WHERE workspace_id = ? AND id = ?",
                ("第 1 章 排序\n快速排序采用分治思想，并适合递归划分。", len("第 1 章 排序\n快速排序采用分治思想，并适合递归划分。"), WORKSPACE_ID, target["id"]),
            )

        second = rag_service.build_index(workspace_id=WORKSPACE_ID)
        assert second["rebuilt_chapters"] == 1
        assert second["reused_chapters"] == 1
    finally:
        _restore_runtime_paths(originals)


def test_parse_cache_reuses_results_across_workspaces(tmp_path: Path, monkeypatch) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_parse_textbook = main.textbooks.parse_textbook
    try:
        init_db()
        source = tmp_path / "生理学.md"
        source.write_text("第 1 章 绪论\n内环境稳态维持生命活动。", encoding="utf-8")

        first = import_textbook_file(source, workspace_id="ws_a")
        assert first["status"] == "completed"

        monkeypatch.setattr(main.textbooks, "parse_textbook", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not parse twice")))
        second = import_textbook_file(source, workspace_id="ws_b")

        assert second["status"] == "completed"
        assert len(second["chapters"]) == len(first["chapters"])
        assert second["total_chars"] == first["total_chars"]
    finally:
        monkeypatch.setattr(main.textbooks, "parse_textbook", original_parse_textbook)
        _restore_runtime_paths(originals)
