from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path

from fastapi import UploadFile

from backend.app.agents.report import ReportAgent
from backend.app.config import settings
from backend.app.db import connect, init_db
from backend.app import main
from backend.app.runtime.store import state_store
from backend.app.runtime.tasks import task_runner
from backend.app.services import graph as graph_service
from backend.app.services import rag as rag_service
from backend.app.services.embedding import embedding_service
from backend.app.services.textbooks import import_textbook_file


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


def test_task_store_dedupes_active_tasks(tmp_path: Path) -> None:
    originals = _set_runtime_paths(tmp_path)
    try:
        init_db()
        first, created = state_store.create_or_get_active_task("build_graph", "textbook", "book-1")
        second, second_created = state_store.create_or_get_active_task("build_graph", "textbook", "book-1")

        assert created is True
        assert second_created is False
        assert first["id"] == second["id"]

        state_store.mark_task_running(first["id"], phase="extracting_graph", progress_total=3)
        state_store.update_task_progress(first["id"], progress_current=2, progress_total=3, truncated=True)
        state_store.succeed_task(first["id"], result_ref="book-1", truncated=True)

        stored = state_store.get_task(first["id"])
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
        payload = asyncio.run(main.upload_textbooks([upload]))

        assert len(payload["uploads"]) == 1
        task_id = payload["uploads"][0]["task"]["id"]
        textbook_id = payload["uploads"][0]["textbook"]["id"]

        task = task_runner.wait_for(task_id)
        assert task["status"] == "succeeded"
        assert task["result_ref"] == textbook_id

        task_response = main.get_task(task_id)
        assert task_response["task"]["status"] == "succeeded"

        textbooks = main.list_textbooks()["textbooks"]
        uploaded = next(item for item in textbooks if item["id"] == textbook_id)
        assert uploaded["status"] == "completed"
        assert uploaded["chapter_count"] >= 1
    finally:
        _restore_runtime_paths(originals)


def test_build_graph_api_reuses_active_task_for_same_textbook(tmp_path: Path, monkeypatch) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_build_graph = graph_service.build_graph
    try:
        init_db()
        source = tmp_path / "算法.md"
        source.write_text("第 1 章 排序\n快速排序采用分治思想。", encoding="utf-8")
        textbook = import_textbook_file(source)

        def slow_build_graph(*args, **kwargs):
            time.sleep(0.2)
            return original_build_graph(*args, **kwargs)

        monkeypatch.setattr(graph_service, "build_graph", slow_build_graph)
        main.startup()
        first = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1})
        second = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1})

        first_task = first["task"]
        second_task = second["task"]
        assert first_task["id"] == second_task["id"]

        finished = task_runner.wait_for(first_task["id"])
        assert finished["status"] == "succeeded"

        graph = main.get_graph(textbook["id"])
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
        textbook = import_textbook_file(source)

        main.startup()
        first = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1})
        task_runner.wait_for(first["task"]["id"])

        second = main.build_graph({"textbook_id": textbook["id"], "max_chapters": 1})
        detail = main.get_task(second["task"]["id"])["task"]

        assert detail["status"] == "succeeded"
        assert detail["phase"] == "cache_hit"
        assert detail["result_ref"] == textbook["id"]
    finally:
        _restore_runtime_paths(originals)


def test_report_pdf_task_failure_is_recorded(tmp_path: Path, monkeypatch) -> None:
    originals = _set_runtime_paths(tmp_path)
    original_generate_pdf = ReportAgent.generate_pdf
    try:
        async def failing_generate_pdf(self):
            raise RuntimeError("pdf engine unavailable")

        monkeypatch.setattr(ReportAgent, "generate_pdf", failing_generate_pdf)
        main.startup()
        response = main.integration_report_pdf_build()
        task_id = response["task"]["id"]

        task = task_runner.wait_for(task_id)
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
        import_textbook_file(source)

        main.startup()
        first = main.build_rag_index()
        task_runner.wait_for(first["task"]["id"])

        second = main.build_rag_index()
        detail = main.get_task(second["task"]["id"])["task"]

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
        textbook = import_textbook_file(source)

        first = rag_service.build_index()
        assert first["rebuilt_chapters"] == 2
        assert first["reused_chapters"] == 0

        chapters = state_store.get_chapters(textbook["id"])
        target = chapters[0]
        with connect() as conn:
            conn.execute(
                "UPDATE chapters SET content = ?, char_count = ? WHERE id = ?",
                ("第 1 章 排序\n快速排序采用分治思想，并适合递归划分。", len("第 1 章 排序\n快速排序采用分治思想，并适合递归划分。"), target["id"]),
            )

        second = rag_service.build_index()
        assert second["rebuilt_chapters"] == 1
        assert second["reused_chapters"] == 1
    finally:
        _restore_runtime_paths(originals)
