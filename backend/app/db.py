from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SQLITE_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
SQLITE_SYNCHRONOUS_MODES = {"OFF", "NORMAL", "FULL", "EXTRA"}


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
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    journal_mode = settings.sqlite_journal_mode if settings.sqlite_journal_mode in SQLITE_JOURNAL_MODES else "DELETE"
    synchronous = settings.sqlite_synchronous if settings.sqlite_synchronous in SQLITE_SYNCHRONOUS_MODES else "NORMAL"
    with connect() as conn:
        conn.execute(f"PRAGMA journal_mode={journal_mode}")
        conn.execute(f"PRAGMA synchronous={synchronous}")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS textbooks (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
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
                workspace_id TEXT NOT NULL DEFAULT 'global',
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
                workspace_id TEXT NOT NULL DEFAULT 'global',
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
                workspace_id TEXT NOT NULL DEFAULT 'global',
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
                workspace_id TEXT NOT NULL DEFAULT 'global',
                textbook_id TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS integration_decisions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
                action TEXT NOT NULL,
                affected_nodes TEXT NOT NULL,
                result_node TEXT,
                reason TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dialogue_messages (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                decision_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
                name TEXT NOT NULL,
                value REAL NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_runs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
                task_type TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                progress_current INTEGER NOT NULL DEFAULT 0,
                progress_total INTEGER NOT NULL DEFAULT 0,
                truncated INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT,
                result_ref TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);
            CREATE INDEX IF NOT EXISTS idx_task_runs_lookup ON task_runs(task_type, resource_type, resource_id, created_at);

            CREATE TABLE IF NOT EXISTS graph_cache_entries (
                textbook_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
                cache_key TEXT NOT NULL,
                chapter_limit INTEGER NOT NULL,
                node_count INTEGER NOT NULL,
                edge_count INTEGER NOT NULL,
                built_at TEXT NOT NULL,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rag_index_entries (
                chapter_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'global',
                textbook_id TEXT NOT NULL,
                chunk_signature TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                built_at TEXT NOT NULL,
                FOREIGN KEY(textbook_id) REFERENCES textbooks(id) ON DELETE CASCADE,
                FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_rag_index_entries_textbook ON rag_index_entries(textbook_id);

            CREATE TABLE IF NOT EXISTS session_workspaces (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workspace_llm_configs (
                workspace_id TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES session_workspaces(id) ON DELETE CASCADE
            );
            """
        )
        _ensure_workspace_columns(conn)
        _ensure_index_metadata_tables(conn)


def is_recoverable_sqlite_error(error: Exception) -> bool:
    message = str(error).lower()
    return "database disk image is malformed" in message or "disk i/o error" in message


def backup_corrupt_database() -> Path | None:
    path = settings.database_path
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.bak")
    path.replace(backup)
    return backup


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_workspace_columns(conn: sqlite3.Connection) -> None:
    workspace_tables = [
        "textbooks",
        "chapters",
        "chunks",
        "knowledge_nodes",
        "knowledge_edges",
        "integration_decisions",
        "dialogue_messages",
        "metrics",
        "task_runs",
        "graph_cache_entries",
        "rag_index_entries",
    ]
    for table in workspace_tables:
        if not _has_column(conn, table, "workspace_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'global'")


def _ensure_index_metadata_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_workspace_status ON task_runs(workspace_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_index_entries_workspace_textbook ON rag_index_entries(workspace_id, textbook_id)")
