from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Any

from ..config import settings
from ..db import connect, json_dumps, json_loads, row_to_dict, utc_now
from .files import runtime_files
from ..utils.ids import new_id


def _task_from_row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    task = row_to_dict(row)
    task["truncated"] = bool(task.get("truncated"))
    task["progress_current"] = int(task.get("progress_current") or 0)
    task["progress_total"] = int(task.get("progress_total") or 0)
    return task


def _workspace_cutoff() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.session_workspace_ttl_seconds)
    return cutoff.isoformat()


class RuntimeStateStore:
    def __init__(self) -> None:
        self._workspace_activity_lock = Lock()
        self._workspace_activity: dict[str, float] = {}
        self._clock = monotonic

    def _should_record_workspace_activity(self, workspace_id: str) -> bool:
        interval = settings.workspace_touch_interval_seconds
        if interval <= 0:
            return True
        now = self._clock()
        with self._workspace_activity_lock:
            last = self._workspace_activity.get(workspace_id)
        return last is None or (now - last) >= interval

    def _record_workspace_activity(self, workspace_id: str) -> None:
        with self._workspace_activity_lock:
            self._workspace_activity[workspace_id] = self._clock()

    def _forget_workspace_activity(self, workspace_id: str) -> None:
        with self._workspace_activity_lock:
            self._workspace_activity.pop(workspace_id, None)

    def clear_legacy_global_state(self) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM rag_index_entries WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM graph_cache_entries WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM chunks WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM knowledge_edges WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM knowledge_nodes WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM chapters WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM integration_decisions WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM dialogue_messages WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM metrics WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM task_runs WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM workspace_llm_configs WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM textbooks WHERE workspace_id = 'global'")
            conn.execute("DELETE FROM session_workspaces WHERE id = 'global'")
        runtime_files.cleanup_legacy_global_layout()

    def ensure_workspace(self, workspace_id: str) -> None:
        if not self._should_record_workspace_activity(workspace_id):
            return
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO session_workspaces (id, created_at, last_active_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET last_active_at = excluded.last_active_at
                """,
                (workspace_id, now, now),
            )
        self._record_workspace_activity(workspace_id)

    def touch_workspace(self, workspace_id: str) -> None:
        if not self._should_record_workspace_activity(workspace_id):
            return
        with connect() as conn:
            conn.execute("UPDATE session_workspaces SET last_active_at = ? WHERE id = ?", (utc_now(), workspace_id))
        self._record_workspace_activity(workspace_id)

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM session_workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if row is None:
            raise KeyError(workspace_id)
        return row_to_dict(row)

    def purge_expired_workspaces(self) -> int:
        cutoff = _workspace_cutoff()
        with connect() as conn:
            rows = conn.execute("SELECT id FROM session_workspaces WHERE last_active_at < ?", (cutoff,)).fetchall()
            workspace_ids = [row["id"] for row in rows]
        for workspace_id in workspace_ids:
            self.delete_workspace(workspace_id)
        return len(workspace_ids)

    def delete_workspace(self, workspace_id: str) -> None:
        with connect() as conn:
            textbook_rows = conn.execute("SELECT id, format FROM textbooks WHERE workspace_id = ?", (workspace_id,)).fetchall()
            textbook_ids = [row["id"] for row in textbook_rows]
            if textbook_ids:
                placeholders = ",".join("?" for _ in textbook_ids)
                conn.execute(f"DELETE FROM chapters WHERE textbook_id IN ({placeholders})", textbook_ids)
                conn.execute(f"DELETE FROM chunks WHERE textbook_id IN ({placeholders})", textbook_ids)
                conn.execute(f"DELETE FROM knowledge_edges WHERE textbook_id IN ({placeholders})", textbook_ids)
                conn.execute(f"DELETE FROM knowledge_nodes WHERE textbook_id IN ({placeholders})", textbook_ids)
                conn.execute(f"DELETE FROM graph_cache_entries WHERE textbook_id IN ({placeholders})", textbook_ids)
            conn.execute("DELETE FROM rag_index_entries WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM integration_decisions WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM dialogue_messages WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM metrics WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM task_runs WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM workspace_llm_configs WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM textbooks WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM session_workspaces WHERE id = ?", (workspace_id,))
        for row in textbook_rows:
            runtime_files.delete_textbook_file(workspace_id, row["id"], row["format"])
        runtime_files.delete_workspace_files(workspace_id)
        self._forget_workspace_activity(workspace_id)

    def create_textbook(self, workspace_id: str, textbook_id: str, filename: str, format_name: str, size_bytes: int, created_at: str | None = None) -> dict[str, Any]:
        self.ensure_workspace(workspace_id)
        created_at = created_at or utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks (id, workspace_id, filename, title, format, size_bytes, total_pages, total_chars, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'parsing', NULL, ?)
                """,
                (textbook_id, workspace_id, filename, filename.rsplit(".", 1)[0], format_name, size_bytes, created_at),
            )
        return self.get_textbook(workspace_id, textbook_id)

    def complete_textbook_parse(self, workspace_id: str, textbook_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
        with connect() as conn:
            conn.execute(
                """
                UPDATE textbooks
                SET title = ?, format = ?, total_pages = ?, total_chars = ?, status = 'completed', error = NULL
                WHERE workspace_id = ? AND id = ?
                """,
                (parsed["title"], parsed["format"], parsed["total_pages"], parsed["total_chars"], workspace_id, textbook_id),
            )
            conn.execute("DELETE FROM chapters WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM knowledge_edges WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM knowledge_nodes WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM graph_cache_entries WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            for position, chapter in enumerate(parsed["chapters"], start=1):
                conn.execute(
                    """
                    INSERT INTO chapters (id, workspace_id, textbook_id, title, page_start, page_end, content, char_count, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("ch"),
                        workspace_id,
                        textbook_id,
                        chapter["title"],
                        chapter["page_start"],
                        chapter["page_end"],
                        chapter["content"],
                        chapter["char_count"],
                        position,
                    ),
                )
        return self.get_textbook(workspace_id, textbook_id)

    def fail_textbook_parse(self, workspace_id: str, textbook_id: str, error_summary: str) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("UPDATE textbooks SET status = 'failed', error = ? WHERE workspace_id = ? AND id = ?", (error_summary, workspace_id, textbook_id))
        return self.get_textbook(workspace_id, textbook_id)

    def delete_textbook(self, workspace_id: str, textbook_id: str) -> None:
        with connect() as conn:
            textbook = conn.execute("SELECT id, format FROM textbooks WHERE workspace_id = ? AND id = ?", (workspace_id, textbook_id)).fetchone()
            if textbook is None:
                raise KeyError(textbook_id)
            chapter_rows = conn.execute("SELECT id FROM chapters WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id)).fetchall()
            chapter_ids = [row["id"] for row in chapter_rows]
            if chapter_ids:
                placeholders = ",".join("?" for _ in chapter_ids)
                params = [workspace_id, *chapter_ids]
                conn.execute(f"DELETE FROM chunks WHERE workspace_id = ? AND chapter_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM rag_index_entries WHERE workspace_id = ? AND chapter_id IN ({placeholders})", params)
            conn.execute("DELETE FROM knowledge_edges WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM knowledge_nodes WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM graph_cache_entries WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM chapters WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM textbooks WHERE workspace_id = ? AND id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM task_runs WHERE workspace_id = ? AND resource_type = 'textbook' AND resource_id = ?", (workspace_id, textbook_id))
        runtime_files.delete_textbook_file(workspace_id, textbook_id, textbook["format"])

    def get_textbook(self, workspace_id: str, textbook_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM textbooks WHERE workspace_id = ? AND id = ?", (workspace_id, textbook_id)).fetchone()
            if row is None:
                raise KeyError(textbook_id)
            textbook = row_to_dict(row)
            textbook["chapters"] = [
                row_to_dict(item)
                for item in conn.execute("SELECT * FROM chapters WHERE workspace_id = ? AND textbook_id = ? ORDER BY position", (workspace_id, textbook_id))
            ]
            node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id)).fetchone()
            edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id)).fetchone()
            textbook["graph_node_count"] = node_count["count"] if node_count else 0
            textbook["graph_edge_count"] = edge_count["count"] if edge_count else 0
            return textbook

    def get_textbook_record(self, workspace_id: str, textbook_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM textbooks WHERE workspace_id = ? AND id = ?", (workspace_id, textbook_id)).fetchone()
            if row is None:
                raise KeyError(textbook_id)
            return row_to_dict(row)

    def list_textbooks(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            textbooks = [row_to_dict(row) for row in conn.execute("SELECT * FROM textbooks WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,))]
            for textbook in textbooks:
                chapter_count = conn.execute("SELECT COUNT(*) AS count FROM chapters WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook["id"])).fetchone()
                node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook["id"])).fetchone()
                edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook["id"])).fetchone()
                textbook["chapter_count"] = chapter_count["count"] if chapter_count else 0
                textbook["graph_node_count"] = node_count["count"] if node_count else 0
                textbook["graph_edge_count"] = edge_count["count"] if edge_count else 0
            return textbooks

    def get_chapters(self, workspace_id: str, textbook_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM chapters WHERE workspace_id = ? AND textbook_id = ? ORDER BY position", (workspace_id, textbook_id))]

    def list_all_chapters(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT id, workspace_id, textbook_id, title, page_start, page_end, content, char_count, position
                    FROM chapters
                    WHERE workspace_id = ?
                    ORDER BY textbook_id, position
                    """,
                    (workspace_id,),
                )
            ]

    def replace_graph(self, workspace_id: str, textbook_id: str, nodes: list[Any], edges: list[Any]) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM knowledge_edges WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            conn.execute("DELETE FROM knowledge_nodes WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))
            for node in nodes:
                conn.execute(
                    """
                    INSERT INTO knowledge_nodes
                    (id, workspace_id, textbook_id, chapter_id, name, definition, category, page, source_excerpt, frequency, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.id,
                        workspace_id,
                        node.textbook_id,
                        node.chapter_id,
                        node.name,
                        node.definition,
                        node.category,
                        node.page,
                        node.source_excerpt,
                        node.frequency,
                        json_dumps(node.metadata),
                    ),
                )
            for edge in edges:
                conn.execute(
                    """
                    INSERT INTO knowledge_edges (id, workspace_id, textbook_id, source, target, relation_type, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (edge.id, workspace_id, edge.textbook_id, edge.source, edge.target, edge.relation_type, edge.description),
                )

    def replace_graph_with_cache(
        self,
        workspace_id: str,
        textbook_id: str,
        nodes: list[Any],
        edges: list[Any],
        *,
        cache_key: str,
        chapter_limit: int,
    ) -> None:
        self.replace_graph(workspace_id, textbook_id, nodes, edges)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_cache_entries (textbook_id, workspace_id, cache_key, chapter_limit, node_count, edge_count, built_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(textbook_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    cache_key = excluded.cache_key,
                    chapter_limit = excluded.chapter_limit,
                    node_count = excluded.node_count,
                    edge_count = excluded.edge_count,
                    built_at = excluded.built_at
                """,
                (textbook_id, workspace_id, cache_key, chapter_limit, len(nodes), len(edges), utc_now()),
            )

    def get_graph(self, workspace_id: str, textbook_id: str) -> dict[str, Any]:
        with connect() as conn:
            nodes = [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT n.*,
                           t.title AS textbook_title,
                           c.title AS chapter_title,
                           c.position AS chapter_position,
                           c.page_start AS page_start,
                           c.page_end AS page_end
                    FROM knowledge_nodes n
                    JOIN textbooks t ON t.id = n.textbook_id
                    JOIN chapters c ON c.id = n.chapter_id
                    WHERE n.workspace_id = ? AND n.textbook_id = ?
                    ORDER BY c.position, n.page, n.name
                    """,
                    (workspace_id, textbook_id),
                )
            ]
            for node in nodes:
                node["metadata"] = json_loads(node.get("metadata"), {})
            edges = [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_edges WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id))]
            textbook = conn.execute("SELECT id, title, filename FROM textbooks WHERE workspace_id = ? AND id = ?", (workspace_id, textbook_id)).fetchone()
            return {
                "textbook": row_to_dict(textbook) if textbook else None,
                "nodes": nodes,
                "edges": edges,
            }

    def get_all_graph_nodes(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT n.*,
                       t.title AS textbook_title,
                       c.title AS chapter_title,
                       c.position AS chapter_position,
                       c.page_start AS page_start,
                       c.page_end AS page_end
                FROM knowledge_nodes n
                JOIN textbooks t ON t.id = n.textbook_id
                JOIN chapters c ON c.id = n.chapter_id
                WHERE n.workspace_id = ?
                ORDER BY t.created_at, c.position, n.page, n.name
                """,
                (workspace_id,),
            )
            nodes = [row_to_dict(row) for row in rows]
            for node in nodes:
                node["metadata"] = json_loads(node.get("metadata"), {})
            return nodes

    def list_all_graph_edges(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_edges WHERE workspace_id = ?", (workspace_id,))]

    def get_graph_cache(self, workspace_id: str, textbook_id: str) -> dict[str, Any] | None:
        with connect() as conn:
            row = conn.execute("SELECT * FROM graph_cache_entries WHERE workspace_id = ? AND textbook_id = ?", (workspace_id, textbook_id)).fetchone()
        return row_to_dict(row) if row is not None else None

    def graph_cache_key(self, workspace_id: str, textbook_id: str, chapter_limit: int) -> str:
        chapters = self.get_chapters(workspace_id, textbook_id)
        selected = chapters[:chapter_limit] if chapter_limit > 0 else chapters
        digest = sha256()
        digest.update(f"{workspace_id}:{textbook_id}:{chapter_limit}:{len(selected)}".encode("utf-8"))
        for chapter in selected:
            digest.update(f"{chapter['position']}|{chapter['title']}|{chapter['page_start']}|{chapter['char_count']}".encode("utf-8"))
            digest.update(chapter["content"].encode("utf-8", errors="ignore"))
        return digest.hexdigest()

    def replace_integration_decisions(self, workspace_id: str, decisions: list[Any]) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM integration_decisions WHERE workspace_id = ?", (workspace_id,))
            for decision in decisions:
                conn.execute(
                    """
                    INSERT INTO integration_decisions (id, workspace_id, action, affected_nodes, result_node, reason, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.id,
                        workspace_id,
                        decision.action,
                        json_dumps(decision.affected_nodes),
                        decision.result_node,
                        decision.reason,
                        decision.confidence,
                        decision.created_at,
                    ),
                )

    def list_integration_decisions(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            decisions = [row_to_dict(row) for row in conn.execute("SELECT * FROM integration_decisions WHERE workspace_id = ? ORDER BY created_at", (workspace_id,))]
        for decision in decisions:
            decision["affected_nodes"] = json_loads(decision["affected_nodes"], [])
        return decisions

    def update_integration_decision(self, workspace_id: str, decision: dict[str, Any]) -> None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE integration_decisions
                SET action = ?, affected_nodes = ?, result_node = ?, reason = ?, confidence = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (
                    decision["action"],
                    json_dumps(decision["affected_nodes"]),
                    decision.get("result_node"),
                    decision["reason"],
                    decision["confidence"],
                    workspace_id,
                    decision["id"],
                ),
            )

    def original_chars(self, workspace_id: str) -> int:
        with connect() as conn:
            return int(conn.execute("SELECT COALESCE(SUM(total_chars), 0) AS total FROM textbooks WHERE workspace_id = ?", (workspace_id,)).fetchone()["total"])

    def replace_chunks(self, workspace_id: str, chunk_rows: list[dict[str, Any]]) -> int:
        with connect() as conn:
            conn.execute("DELETE FROM chunks WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM rag_index_entries WHERE workspace_id = ?", (workspace_id,))
            for chunk in chunk_rows:
                conn.execute(
                    """
                    INSERT INTO chunks (id, workspace_id, textbook_id, chapter_id, chunk_index, text, page_start, char_count, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
                        workspace_id,
                        chunk["textbook_id"],
                        chunk["chapter_id"],
                        chunk["chunk_index"],
                        chunk["text"],
                        chunk["page_start"],
                        chunk["char_count"],
                        chunk["embedding"],
                    ),
                )
        return len(chunk_rows)

    def replace_chunks_for_chapters(
        self,
        workspace_id: str,
        chapter_ids: list[str],
        chunk_rows: list[dict[str, Any]],
        index_entries: list[dict[str, Any]],
        *,
        deleted_chapter_ids: list[str] | None = None,
    ) -> int:
        deleted = list(deleted_chapter_ids or [])
        targets = sorted(set(chapter_ids + deleted))
        with connect() as conn:
            if targets:
                placeholders = ",".join("?" for _ in targets)
                params = [workspace_id, *targets]
                conn.execute(f"DELETE FROM chunks WHERE workspace_id = ? AND chapter_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM rag_index_entries WHERE workspace_id = ? AND chapter_id IN ({placeholders})", params)
            for chunk in chunk_rows:
                conn.execute(
                    """
                    INSERT INTO chunks (id, workspace_id, textbook_id, chapter_id, chunk_index, text, page_start, char_count, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
                        workspace_id,
                        chunk["textbook_id"],
                        chunk["chapter_id"],
                        chunk["chunk_index"],
                        chunk["text"],
                        chunk["page_start"],
                        chunk["char_count"],
                        chunk["embedding"],
                    ),
                )
            for entry in index_entries:
                conn.execute(
                    """
                    INSERT INTO rag_index_entries (chapter_id, workspace_id, textbook_id, chunk_signature, chunk_count, built_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry["chapter_id"],
                        workspace_id,
                        entry["textbook_id"],
                        entry["chunk_signature"],
                        entry["chunk_count"],
                        entry["built_at"],
                    ),
                )
        return len(chunk_rows)

    def list_chunks_with_context(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT chunks.*, textbooks.title AS textbook, chapters.title AS chapter
                    FROM chunks
                    JOIN textbooks ON textbooks.id = chunks.textbook_id
                    JOIN chapters ON chapters.id = chunks.chapter_id
                    WHERE chunks.workspace_id = ?
                    """,
                    (workspace_id,),
                )
            ]

    def count_chunks(self, workspace_id: str) -> int:
        with connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM chunks WHERE workspace_id = ?", (workspace_id,)).fetchone()["count"])

    def count_completed_textbooks(self, workspace_id: str) -> int:
        with connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM textbooks WHERE workspace_id = ? AND status = 'completed'", (workspace_id,)).fetchone()["count"])

    def list_rag_index_entries(self, workspace_id: str) -> dict[str, dict[str, Any]]:
        with connect() as conn:
            rows = conn.execute("SELECT * FROM rag_index_entries WHERE workspace_id = ?", (workspace_id,)).fetchall()
        return {row["chapter_id"]: row_to_dict(row) for row in rows}

    def rag_index_signature(self, chapter: dict[str, Any]) -> str:
        digest = sha256()
        digest.update(
            f"{chapter.get('workspace_id', 'global')}|{chapter['chapter_id'] if 'chapter_id' in chapter else chapter['id']}|{chapter['textbook_id']}|{chapter['position']}|{chapter['page_start']}|{chapter['char_count']}".encode(
                "utf-8"
            )
        )
        digest.update(chapter["content"].encode("utf-8", errors="ignore"))
        return digest.hexdigest()

    def rag_index_freshness(self, workspace_id: str) -> tuple[bool, int]:
        chapters = self.list_all_chapters(workspace_id)
        entries = self.list_rag_index_entries(workspace_id)
        if len(chapters) != len(entries):
            return False, len(chapters)
        for chapter in chapters:
            entry = entries.get(chapter["id"])
            if entry is None or entry["chunk_signature"] != self.rag_index_signature(chapter):
                return False, len(chapters)
        return True, len(chapters)

    def append_dialogue_message(self, workspace_id: str, role: str, message: str, decision_id: str | None = None) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO dialogue_messages (id, workspace_id, role, message, decision_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("msg"), workspace_id, role, message, decision_id, utc_now()),
            )

    def list_dialogue_messages(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM dialogue_messages WHERE workspace_id = ? ORDER BY created_at", (workspace_id,))]

    def insert_metric(self, workspace_id: str, name: str, value: float, metadata: dict[str, Any]) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO metrics (id, workspace_id, name, value, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("metric"), workspace_id, name, value, json_dumps(metadata), utc_now()),
            )

    def recent_metrics(self, workspace_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM metrics WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?", (workspace_id, limit))]

    def collect_report_data(self, workspace_id: str) -> dict[str, Any]:
        with connect() as conn:
            textbooks = [row_to_dict(row) for row in conn.execute("SELECT * FROM textbooks WHERE workspace_id = ? ORDER BY created_at", (workspace_id,))]
            nodes = {row["id"]: row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_nodes WHERE workspace_id = ?", (workspace_id,))}
            node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes WHERE workspace_id = ?", (workspace_id,)).fetchone()["count"]
            edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges WHERE workspace_id = ?", (workspace_id,)).fetchone()["count"]
            decisions = [row_to_dict(row) for row in conn.execute("SELECT * FROM integration_decisions WHERE workspace_id = ? ORDER BY created_at", (workspace_id,))]
            metrics = [row_to_dict(row) for row in conn.execute("SELECT * FROM metrics WHERE workspace_id = ? ORDER BY created_at DESC LIMIT 20", (workspace_id,))]
        for decision in decisions:
            decision["affected_nodes"] = json_loads(decision["affected_nodes"], [])
        return {
            "textbooks": textbooks,
            "nodes": nodes,
            "node_count": node_count,
            "edge_count": edge_count,
            "decisions": decisions,
            "metrics": metrics,
        }

    def set_workspace_llm_config(self, workspace_id: str, base_url: str, api_key: str, model: str) -> None:
        self.ensure_workspace(workspace_id)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_llm_configs (workspace_id, base_url, api_key, model, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    base_url = excluded.base_url,
                    api_key = excluded.api_key,
                    model = excluded.model,
                    updated_at = excluded.updated_at
                """,
                (workspace_id, base_url, api_key, model, utc_now()),
            )

    def get_workspace_llm_config(self, workspace_id: str) -> dict[str, Any] | None:
        with connect() as conn:
            row = conn.execute("SELECT * FROM workspace_llm_configs WHERE workspace_id = ?", (workspace_id,)).fetchone()
        return row_to_dict(row) if row is not None else None

    def delete_workspace_llm_config(self, workspace_id: str) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM workspace_llm_configs WHERE workspace_id = ?", (workspace_id,))

    def create_or_get_active_task(self, workspace_id: str, task_type: str, resource_type: str, resource_id: str, phase: str = "queued") -> tuple[dict[str, Any], bool]:
        self.ensure_workspace(workspace_id)
        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM task_runs
                WHERE workspace_id = ? AND task_type = ? AND resource_type = ? AND resource_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id, task_type, resource_type, resource_id),
            ).fetchone()
            if row is not None:
                return _task_from_row(row), False
            task_id = new_id("task")
            created_at = utc_now()
            conn.execute(
                """
                INSERT INTO task_runs
                (id, workspace_id, task_type, resource_type, resource_id, status, phase, created_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (task_id, workspace_id, task_type, resource_type, resource_id, phase, created_at),
            )
            row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
            return _task_from_row(row), True

    def create_finished_task(
        self,
        workspace_id: str,
        task_type: str,
        resource_type: str,
        resource_id: str,
        *,
        phase: str,
        result_ref: str | None = None,
        truncated: bool = False,
        error_summary: str | None = None,
        progress_current: int = 0,
        progress_total: int = 0,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_id)
        status = "failed" if error_summary else "succeeded"
        created_at = utc_now()
        task_id = new_id("task")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO task_runs
                (id, workspace_id, task_type, resource_type, resource_id, status, phase, progress_current, progress_total, truncated, error_summary, result_ref, created_at, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    workspace_id,
                    task_type,
                    resource_type,
                    resource_id,
                    status,
                    phase,
                    progress_current,
                    progress_total,
                    1 if truncated else 0,
                    error_summary,
                    result_ref,
                    created_at,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(row)

    def get_task(self, workspace_id: str, task_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM task_runs WHERE workspace_id = ? AND id = ?", (workspace_id, task_id)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return _task_from_row(row)

    def list_tasks(
        self,
        workspace_id: str,
        status: str | None = None,
        task_type: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        if resource_type:
            clauses.append("resource_type = ?")
            params.append(resource_type)
        if resource_id:
            clauses.append("resource_id = ?")
            params.append(resource_id)
        where = f"WHERE {' AND '.join(clauses)}"
        with connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM task_runs {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def mark_task_running(self, workspace_id: str, task_id: str, phase: str = "running", progress_total: int | None = None) -> None:
        with connect() as conn:
            if progress_total is None:
                conn.execute(
                    "UPDATE task_runs SET status = 'running', phase = ?, started_at = COALESCE(started_at, ?) WHERE workspace_id = ? AND id = ?",
                    (phase, utc_now(), workspace_id, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE task_runs
                    SET status = 'running', phase = ?, started_at = COALESCE(started_at, ?), progress_total = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (phase, utc_now(), progress_total, workspace_id, task_id),
                )

    def update_task_progress(
        self,
        workspace_id: str,
        task_id: str,
        *,
        phase: str | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        truncated: bool | None = None,
    ) -> None:
        assignments = []
        params: list[Any] = []
        if phase is not None:
            assignments.append("phase = ?")
            params.append(phase)
        if progress_current is not None:
            assignments.append("progress_current = ?")
            params.append(progress_current)
        if progress_total is not None:
            assignments.append("progress_total = ?")
            params.append(progress_total)
        if truncated is not None:
            assignments.append("truncated = ?")
            params.append(1 if truncated else 0)
        if not assignments:
            return
        params.extend([workspace_id, task_id])
        with connect() as conn:
            conn.execute(f"UPDATE task_runs SET {', '.join(assignments)} WHERE workspace_id = ? AND id = ?", params)

    def succeed_task(self, workspace_id: str, task_id: str, *, result_ref: str | None = None, truncated: bool = False, phase: str = "completed") -> None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'succeeded', phase = ?, truncated = ?, result_ref = ?, error_summary = NULL, finished_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (phase, 1 if truncated else 0, result_ref, utc_now(), workspace_id, task_id),
            )

    def fail_task(self, workspace_id: str, task_id: str, error_summary: str, phase: str = "failed") -> None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'failed', phase = ?, error_summary = ?, finished_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (phase, error_summary, utc_now(), workspace_id, task_id),
            )

    def fail_stale_tasks(self, error_summary: str = "Task interrupted by application restart.") -> int:
        with connect() as conn:
            active_rows = conn.execute("SELECT workspace_id, id FROM task_runs WHERE status IN ('queued', 'running')").fetchall()
            if not active_rows:
                return 0
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'failed', phase = 'failed', error_summary = ?, finished_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (error_summary, utc_now()),
            )
        return len(active_rows)


state_store = RuntimeStateStore()
