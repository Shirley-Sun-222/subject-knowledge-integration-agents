from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path: Path = settings.database_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS textbooks (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                title TEXT NOT NULL,
                format TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                total_pages INTEGER NOT NULL DEFAULT 0,
                total_chars INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                textbook_id TEXT NOT NULL,
                title TEXT NOT NULL,
                page_start INTEGER NOT NULL,
                page_end INTEGER NOT NULL,
                content TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                position INTEGER NOT NULL,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                textbook_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                page_start INTEGER NOT NULL,
                char_count INTEGER NOT NULL,
                embedding TEXT,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE,
                FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id TEXT PRIMARY KEY,
                textbook_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                name TEXT NOT NULL,
                definition TEXT NOT NULL,
                category TEXT NOT NULL,
                page INTEGER NOT NULL,
                source_excerpt TEXT NOT NULL,
                frequency INTEGER NOT NULL DEFAULT 1,
                metadata TEXT,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE,
                FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id TEXT PRIMARY KEY,
                textbook_id TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS integration_decisions (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                affected_nodes TEXT NOT NULL,
                result_node TEXT,
                reason TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dialogue_messages (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                decision_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

