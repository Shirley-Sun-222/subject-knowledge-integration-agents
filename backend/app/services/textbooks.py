from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from ..runtime.files import runtime_files
from ..runtime.store import state_store
from ..runtime.tasks import TaskContext, task_runner
from ..services.parser import ParseError, parse_textbook
from ..utils.ids import new_id


async def save_upload(file: UploadFile) -> dict:
    textbook_id = new_id("book")
    suffix = Path(file.filename or "textbook.txt").suffix.lower()
    format_name = suffix.replace(".", "") or "txt"
    filename = file.filename or f"{textbook_id}{suffix or '.txt'}"
    _, size = await runtime_files.save_upload(textbook_id, file, format_name)
    return state_store.create_textbook(textbook_id, filename, format_name, size)


def enqueue_parse_textbook(textbook_id: str) -> tuple[dict, bool]:
    return task_runner.enqueue(
        "parse_textbook",
        "textbook",
        textbook_id,
        lambda context: _parse_textbook_task(context, textbook_id),
    )


def import_textbook_file(source: Path, original_filename: str | None = None) -> dict:
    textbook_id = new_id("book")
    source = source.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    format_name = suffix.replace(".", "") or "txt"
    runtime_files.copy_upload(textbook_id, source, format_name)
    filename = original_filename or source.name
    state_store.create_textbook(textbook_id, filename, format_name, source.stat().st_size)
    return parse_stored_textbook(textbook_id)


def parse_stored_textbook(textbook_id: str) -> dict:
    return parse_stored_textbook_with_progress(textbook_id)


def parse_stored_textbook_with_progress(textbook_id: str, progress: TaskContext | None = None) -> dict:
    textbook = state_store.get_textbook_record(textbook_id)
    destination = runtime_files.stored_textbook_path(textbook_id, textbook["format"])
    try:
        parsed = parse_textbook(
            destination,
            textbook["filename"],
            progress=(lambda phase, current, total: progress.progress(phase=phase, progress_current=current, progress_total=total)) if progress else None,
        )
        return state_store.complete_textbook_parse(textbook_id, parsed)
    except Exception as exc:
        error_message = str(exc)
        if isinstance(exc, ParseError):
            error_message = str(exc)
        return state_store.fail_textbook_parse(textbook_id, error_message)


def _parse_textbook_task(context: TaskContext, textbook_id: str) -> dict:
    context.start("parsing_textbook", progress_total=1)
    textbook = parse_stored_textbook_with_progress(textbook_id, progress=context)
    if textbook["status"] != "completed":
        raise RuntimeError(textbook.get("error") or "Failed to parse textbook")
    context.progress(phase="writing_textbook", progress_current=1, progress_total=1)
    return {
        "result_ref": textbook_id,
        "phase": "completed",
        "truncated": False,
    }


def get_textbook(textbook_id: str) -> dict:
    return state_store.get_textbook(textbook_id)


def list_textbooks() -> list[dict]:
    return state_store.list_textbooks()
