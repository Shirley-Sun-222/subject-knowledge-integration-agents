from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile

from ..config import settings
from ..db import connect, row_to_dict, utc_now
from ..services.parser import parse_textbook
from ..utils.ids import new_id


async def save_and_parse_upload(file: UploadFile) -> dict:
    textbook_id = new_id("book")
    suffix = Path(file.filename or "textbook.txt").suffix.lower()
    safe_name = f"{textbook_id}{suffix}"
    destination = settings.upload_dir / safe_name
    size = 0
    with destination.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            buffer.write(chunk)

    filename = file.filename or safe_name
    created_at = utc_now()
    _insert_textbook_record(textbook_id, filename, suffix, size, created_at)
    return _parse_stored_textbook(textbook_id, destination, filename)


def import_textbook_file(source: Path, original_filename: str | None = None) -> dict:
    textbook_id = new_id("book")
    source = source.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    safe_name = f"{textbook_id}{suffix}"
    destination = settings.upload_dir / safe_name
    shutil.copy2(source, destination)
    filename = original_filename or source.name
    _insert_textbook_record(textbook_id, filename, suffix, destination.stat().st_size, utc_now())
    return _parse_stored_textbook(textbook_id, destination, filename)


def _insert_textbook_record(textbook_id: str, filename: str, suffix: str, size: int, created_at: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO textbooks (id, filename, title, format, size_bytes, total_pages, total_chars, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, 0, 0, 'parsing', NULL, ?)
            """,
            (textbook_id, filename, Path(filename).stem, suffix.replace(".", ""), size, created_at),
        )


def _parse_stored_textbook(textbook_id: str, destination: Path, filename: str) -> dict:
    try:
        parsed = parse_textbook(destination, filename)
        with connect() as conn:
            conn.execute(
                """
                UPDATE textbooks
                SET title = ?, format = ?, total_pages = ?, total_chars = ?, status = 'completed', error = NULL
                WHERE id = ?
                """,
                (parsed["title"], parsed["format"], parsed["total_pages"], parsed["total_chars"], textbook_id),
            )
            conn.execute("DELETE FROM chapters WHERE textbook_id = ?", (textbook_id,))
            for position, chapter in enumerate(parsed["chapters"], start=1):
                chapter_id = new_id("ch")
                conn.execute(
                    """
                    INSERT INTO chapters (id, textbook_id, title, page_start, page_end, content, char_count, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chapter_id,
                        textbook_id,
                        chapter["title"],
                        chapter["page_start"],
                        chapter["page_end"],
                        chapter["content"],
                        chapter["char_count"],
                        position,
                    ),
                )
        return get_textbook(textbook_id)
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE textbooks SET status = 'failed', error = ? WHERE id = ?", (str(exc), textbook_id))
        return get_textbook(textbook_id)


def get_textbook(textbook_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM textbooks WHERE id = ?", (textbook_id,)).fetchone()
        if row is None:
            raise KeyError(textbook_id)
        textbook = row_to_dict(row)
        chapters = [row_to_dict(item) for item in conn.execute("SELECT * FROM chapters WHERE textbook_id = ? ORDER BY position", (textbook_id,))]
        textbook["chapters"] = chapters
        return textbook


def list_textbooks() -> list[dict]:
    with connect() as conn:
        textbooks = [row_to_dict(row) for row in conn.execute("SELECT * FROM textbooks ORDER BY created_at DESC")]
        for textbook in textbooks:
            textbook["chapters"] = [
                row_to_dict(row)
                for row in conn.execute("SELECT * FROM chapters WHERE textbook_id = ? ORDER BY position", (textbook["id"],))
            ]
            node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes WHERE textbook_id = ?", (textbook["id"],)).fetchone()
            edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges WHERE textbook_id = ?", (textbook["id"],)).fetchone()
            textbook["graph_node_count"] = node_count["count"] if node_count else 0
            textbook["graph_edge_count"] = edge_count["count"] if edge_count else 0
        return textbooks
