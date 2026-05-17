from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from ..config import settings
from ..runtime.files import runtime_files
from ..runtime.store import state_store
from ..runtime.tasks import TaskContext, task_runner
from ..services.parser import ParseError, parse_textbook
from ..utils.ids import new_id


async def save_upload(file: UploadFile, workspace_id: str = "global") -> dict:
    textbook_id = new_id("book")
    suffix = Path(file.filename or "textbook.txt").suffix.lower()
    format_name = suffix.replace(".", "") or "txt"
    filename = file.filename or f"{textbook_id}{suffix or '.txt'}"
    _, size, file_hash = await runtime_files.save_upload(workspace_id, textbook_id, file, format_name)
    return state_store.create_textbook(workspace_id, textbook_id, filename, format_name, size, file_hash=file_hash)


def enqueue_parse_textbook(textbook_id: str, workspace_id: str = "global") -> tuple[dict, bool]:
    return task_runner.enqueue(
        workspace_id,
        "parse_textbook",
        "textbook",
        textbook_id,
        lambda context: _parse_textbook_task(context, textbook_id, workspace_id=workspace_id),
    )


def import_textbook_file(source: Path, original_filename: str | None = None, workspace_id: str = "global") -> dict:
    textbook_id = new_id("book")
    source = source.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    format_name = suffix.replace(".", "") or "txt"
    _, file_hash = runtime_files.copy_upload(workspace_id, textbook_id, source, format_name)
    filename = original_filename or source.name
    state_store.create_textbook(workspace_id, textbook_id, filename, format_name, source.stat().st_size, file_hash=file_hash)
    return parse_stored_textbook(textbook_id, workspace_id=workspace_id)


def parse_stored_textbook(textbook_id: str, workspace_id: str = "global") -> dict:
    return parse_stored_textbook_with_progress(textbook_id, workspace_id=workspace_id)


def parse_stored_textbook_with_progress(textbook_id: str, progress: TaskContext | None = None, workspace_id: str = "global") -> dict:
    textbook = state_store.get_textbook_record(workspace_id, textbook_id)
    destination = runtime_files.stored_textbook_path(workspace_id, textbook_id, textbook["format"])
    try:
        file_hash = textbook.get("file_hash")
        if settings.parse_cache_enabled and file_hash:
            cached = state_store.get_parsed_textbook_cache(file_hash)
            if cached is not None:
                if progress is not None:
                    progress.progress(phase="reusing_cached_parse", progress_current=1, progress_total=1)
                parsed = {
                    "filename": textbook["filename"],
                    "title": cached["title"],
                    "format": cached["format"],
                    "total_pages": cached["total_pages"],
                    "total_chars": cached["total_chars"],
                    "chapters": cached["chapters"],
                }
                return state_store.complete_textbook_parse(workspace_id, textbook_id, parsed)
        parsed = parse_textbook(
            destination,
            textbook["filename"],
            progress=(lambda phase, current, total: progress.progress(phase=phase, progress_current=current, progress_total=total)) if progress else None,
        )
        if settings.parse_cache_enabled and file_hash:
            state_store.store_parsed_textbook_cache(file_hash, textbook["format"], parsed)
        return state_store.complete_textbook_parse(workspace_id, textbook_id, parsed)
    except Exception as exc:
        error_message = str(exc)
        if isinstance(exc, ParseError):
            error_message = str(exc)
        return state_store.fail_textbook_parse(workspace_id, textbook_id, error_message)


def _parse_textbook_task(context: TaskContext, textbook_id: str, workspace_id: str = "global") -> dict:
    context.start("parsing_textbook", progress_total=1)
    textbook = parse_stored_textbook_with_progress(textbook_id, progress=context, workspace_id=workspace_id)
    if textbook["status"] != "completed":
        raise RuntimeError(textbook.get("error") or "Failed to parse textbook")
    context.progress(phase="writing_textbook", progress_current=1, progress_total=1)
    return {
        "result_ref": textbook_id,
        "phase": "completed",
        "truncated": False,
    }


def get_textbook(textbook_id: str, workspace_id: str = "global") -> dict:
    return state_store.get_textbook(workspace_id, textbook_id)


def list_textbooks(workspace_id: str = "global") -> list[dict]:
    return state_store.list_textbooks(workspace_id)


def delete_textbook(textbook_id: str, workspace_id: str = "global") -> None:
    state_store.delete_textbook(workspace_id, textbook_id)
