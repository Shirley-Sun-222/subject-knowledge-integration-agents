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
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO textbooks (id, filename, title, format, size_bytes, total_pages, total_chars, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, 0, 0, 'parsing', NULL, ?)
            """,
            (textbook_id, filename, Path(filename).stem, suffix.replace(".", ""), size, created_at),
        )

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
        return textbooks

