from __future__ import annotations

from hashlib import sha256
from typing import Any

from ..db import connect, json_dumps, json_loads, row_to_dict, utc_now
from ..utils.ids import new_id


def _task_from_row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    task = row_to_dict(row)
    task["truncated"] = bool(task.get("truncated"))
    task["progress_current"] = int(task.get("progress_current") or 0)
    task["progress_total"] = int(task.get("progress_total") or 0)
    return task


class RuntimeStateStore:
    def create_textbook(self, textbook_id: str, filename: str, format_name: str, size_bytes: int, created_at: str | None = None) -> dict[str, Any]:
        created_at = created_at or utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO textbooks (id, filename, title, format, size_bytes, total_pages, total_chars, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, 'parsing', NULL, ?)
                """,
                (textbook_id, filename, filename.rsplit(".", 1)[0], format_name, size_bytes, created_at),
            )
        return self.get_textbook(textbook_id)

    def complete_textbook_parse(self, textbook_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
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
            conn.execute("DELETE FROM knowledge_edges WHERE textbook_id = ?", (textbook_id,))
            conn.execute("DELETE FROM knowledge_nodes WHERE textbook_id = ?", (textbook_id,))
            conn.execute("DELETE FROM graph_cache_entries WHERE textbook_id = ?", (textbook_id,))
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
        return self.get_textbook(textbook_id)

    def fail_textbook_parse(self, textbook_id: str, error_summary: str) -> dict[str, Any]:
        with connect() as conn:
            conn.execute("UPDATE textbooks SET status = 'failed', error = ? WHERE id = ?", (error_summary, textbook_id))
        return self.get_textbook(textbook_id)

    def get_textbook(self, textbook_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM textbooks WHERE id = ?", (textbook_id,)).fetchone()
            if row is None:
                raise KeyError(textbook_id)
            textbook = row_to_dict(row)
            textbook["chapters"] = [
                row_to_dict(item)
                for item in conn.execute("SELECT * FROM chapters WHERE textbook_id = ? ORDER BY position", (textbook_id,))
            ]
            node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes WHERE textbook_id = ?", (textbook_id,)).fetchone()
            edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges WHERE textbook_id = ?", (textbook_id,)).fetchone()
            textbook["graph_node_count"] = node_count["count"] if node_count else 0
            textbook["graph_edge_count"] = edge_count["count"] if edge_count else 0
            return textbook

    def get_textbook_record(self, textbook_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM textbooks WHERE id = ?", (textbook_id,)).fetchone()
            if row is None:
                raise KeyError(textbook_id)
            return row_to_dict(row)

    def list_textbooks(self) -> list[dict[str, Any]]:
        with connect() as conn:
            textbooks = [row_to_dict(row) for row in conn.execute("SELECT * FROM textbooks ORDER BY created_at DESC")]
            for textbook in textbooks:
                chapter_count = conn.execute("SELECT COUNT(*) AS count FROM chapters WHERE textbook_id = ?", (textbook["id"],)).fetchone()
                node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes WHERE textbook_id = ?", (textbook["id"],)).fetchone()
                edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges WHERE textbook_id = ?", (textbook["id"],)).fetchone()
                textbook["chapter_count"] = chapter_count["count"] if chapter_count else 0
                textbook["graph_node_count"] = node_count["count"] if node_count else 0
                textbook["graph_edge_count"] = edge_count["count"] if edge_count else 0
            return textbooks

    def get_chapters(self, textbook_id: str) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM chapters WHERE textbook_id = ? ORDER BY position", (textbook_id,))]

    def list_all_chapters(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT id, textbook_id, title, page_start, page_end, content, char_count, position
                    FROM chapters
                    ORDER BY textbook_id, position
                    """
                )
            ]

    def replace_graph(self, textbook_id: str, nodes: list[Any], edges: list[Any]) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM knowledge_edges WHERE textbook_id = ?", (textbook_id,))
            conn.execute("DELETE FROM knowledge_nodes WHERE textbook_id = ?", (textbook_id,))
            for node in nodes:
                conn.execute(
                    """
                    INSERT INTO knowledge_nodes
                    (id, textbook_id, chapter_id, name, definition, category, page, source_excerpt, frequency, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.id,
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
                    INSERT INTO knowledge_edges (id, textbook_id, source, target, relation_type, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (edge.id, edge.textbook_id, edge.source, edge.target, edge.relation_type, edge.description),
                )

    def replace_graph_with_cache(
        self,
        textbook_id: str,
        nodes: list[Any],
        edges: list[Any],
        *,
        cache_key: str,
        chapter_limit: int,
    ) -> None:
        self.replace_graph(textbook_id, nodes, edges)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_cache_entries (textbook_id, cache_key, chapter_limit, node_count, edge_count, built_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(textbook_id) DO UPDATE SET
                    cache_key = excluded.cache_key,
                    chapter_limit = excluded.chapter_limit,
                    node_count = excluded.node_count,
                    edge_count = excluded.edge_count,
                    built_at = excluded.built_at
                """,
                (textbook_id, cache_key, chapter_limit, len(nodes), len(edges), utc_now()),
            )

    def get_graph(self, textbook_id: str) -> dict[str, Any]:
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
                    WHERE n.textbook_id = ?
                    ORDER BY c.position, n.page, n.name
                    """,
                    (textbook_id,),
                )
            ]
            for node in nodes:
                node["metadata"] = json_loads(node.get("metadata"), {})
            edges = [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_edges WHERE textbook_id = ?", (textbook_id,))]
            textbook = conn.execute("SELECT id, title, filename FROM textbooks WHERE id = ?", (textbook_id,)).fetchone()
            return {
                "textbook": row_to_dict(textbook) if textbook else None,
                "nodes": nodes,
                "edges": edges,
            }

    def get_all_graph_nodes(self) -> list[dict[str, Any]]:
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
                ORDER BY t.created_at, c.position, n.page, n.name
                """
            )
            nodes = [row_to_dict(row) for row in rows]
            for node in nodes:
                node["metadata"] = json_loads(node.get("metadata"), {})
            return nodes

    def list_all_graph_edges(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_edges")]

    def get_graph_cache(self, textbook_id: str) -> dict[str, Any] | None:
        with connect() as conn:
            row = conn.execute("SELECT * FROM graph_cache_entries WHERE textbook_id = ?", (textbook_id,)).fetchone()
        return row_to_dict(row) if row is not None else None

    def graph_cache_key(self, textbook_id: str, chapter_limit: int) -> str:
        chapters = self.get_chapters(textbook_id)
        selected = chapters[:chapter_limit] if chapter_limit > 0 else chapters
        digest = sha256()
        digest.update(f"{textbook_id}:{chapter_limit}:{len(selected)}".encode("utf-8"))
        for chapter in selected:
            digest.update(f"{chapter['position']}|{chapter['title']}|{chapter['page_start']}|{chapter['char_count']}".encode("utf-8"))
            digest.update(chapter["content"].encode("utf-8", errors="ignore"))
        return digest.hexdigest()

    def replace_integration_decisions(self, decisions: list[Any]) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM integration_decisions")
            for decision in decisions:
                conn.execute(
                    """
                    INSERT INTO integration_decisions (id, action, affected_nodes, result_node, reason, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.id,
                        decision.action,
                        json_dumps(decision.affected_nodes),
                        decision.result_node,
                        decision.reason,
                        decision.confidence,
                        decision.created_at,
                    ),
                )

    def list_integration_decisions(self) -> list[dict[str, Any]]:
        with connect() as conn:
            decisions = [row_to_dict(row) for row in conn.execute("SELECT * FROM integration_decisions ORDER BY created_at")]
        for decision in decisions:
            decision["affected_nodes"] = json_loads(decision["affected_nodes"], [])
        return decisions

    def update_integration_decision(self, decision: dict[str, Any]) -> None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE integration_decisions
                SET action = ?, affected_nodes = ?, result_node = ?, reason = ?, confidence = ?
                WHERE id = ?
                """,
                (
                    decision["action"],
                    json_dumps(decision["affected_nodes"]),
                    decision.get("result_node"),
                    decision["reason"],
                    decision["confidence"],
                    decision["id"],
                ),
            )

    def original_chars(self) -> int:
        with connect() as conn:
            return int(conn.execute("SELECT COALESCE(SUM(total_chars), 0) AS total FROM textbooks").fetchone()["total"])

    def replace_chunks(self, chunk_rows: list[dict[str, Any]]) -> int:
        with connect() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM rag_index_entries")
            for chunk in chunk_rows:
                conn.execute(
                    """
                    INSERT INTO chunks (id, textbook_id, chapter_id, chunk_index, text, page_start, char_count, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
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
                conn.execute(f"DELETE FROM chunks WHERE chapter_id IN ({placeholders})", targets)
                conn.execute(f"DELETE FROM rag_index_entries WHERE chapter_id IN ({placeholders})", targets)
            for chunk in chunk_rows:
                conn.execute(
                    """
                    INSERT INTO chunks (id, textbook_id, chapter_id, chunk_index, text, page_start, char_count, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
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
                    INSERT INTO rag_index_entries (chapter_id, textbook_id, chunk_signature, chunk_count, built_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        entry["chapter_id"],
                        entry["textbook_id"],
                        entry["chunk_signature"],
                        entry["chunk_count"],
                        entry["built_at"],
                    ),
                )
        return len(chunk_rows)

    def list_chunks_with_context(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return [
                row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT chunks.*, textbooks.title AS textbook, chapters.title AS chapter
                    FROM chunks
                    JOIN textbooks ON textbooks.id = chunks.textbook_id
                    JOIN chapters ON chapters.id = chunks.chapter_id
                    """
                )
            ]

    def count_chunks(self) -> int:
        with connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()["count"])

    def count_completed_textbooks(self) -> int:
        with connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS count FROM textbooks WHERE status = 'completed'").fetchone()["count"])

    def list_rag_index_entries(self) -> dict[str, dict[str, Any]]:
        with connect() as conn:
            rows = conn.execute("SELECT * FROM rag_index_entries").fetchall()
        return {row["chapter_id"]: row_to_dict(row) for row in rows}

    def rag_index_signature(self, chapter: dict[str, Any]) -> str:
        digest = sha256()
        digest.update(
            f"{chapter['chapter_id'] if 'chapter_id' in chapter else chapter['id']}|{chapter['textbook_id']}|{chapter['position']}|{chapter['page_start']}|{chapter['char_count']}".encode(
                "utf-8"
            )
        )
        digest.update(chapter["content"].encode("utf-8", errors="ignore"))
        return digest.hexdigest()

    def rag_index_freshness(self) -> tuple[bool, int]:
        chapters = self.list_all_chapters()
        entries = self.list_rag_index_entries()
        if len(chapters) != len(entries):
            return False, len(chapters)
        for chapter in chapters:
            entry = entries.get(chapter["id"])
            if entry is None or entry["chunk_signature"] != self.rag_index_signature(chapter):
                return False, len(chapters)
        return True, len(chapters)

    def append_dialogue_message(self, role: str, message: str, decision_id: str | None = None) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO dialogue_messages (id, role, message, decision_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("msg"), role, message, decision_id, utc_now()),
            )

    def list_dialogue_messages(self) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM dialogue_messages ORDER BY created_at")]

    def insert_metric(self, name: str, value: float, metadata: dict[str, Any]) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO metrics (id, name, value, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("metric"), name, value, json_dumps(metadata), utc_now()),
            )

    def recent_metrics(self, limit: int = 20) -> list[dict[str, Any]]:
        with connect() as conn:
            return [row_to_dict(row) for row in conn.execute("SELECT * FROM metrics ORDER BY created_at DESC LIMIT ?", (limit,))]

    def collect_report_data(self) -> dict[str, Any]:
        with connect() as conn:
            textbooks = [row_to_dict(row) for row in conn.execute("SELECT * FROM textbooks ORDER BY created_at")]
            nodes = {row["id"]: row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_nodes")}
            node_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_nodes").fetchone()["count"]
            edge_count = conn.execute("SELECT COUNT(*) AS count FROM knowledge_edges").fetchone()["count"]
            decisions = [row_to_dict(row) for row in conn.execute("SELECT * FROM integration_decisions ORDER BY created_at")]
            metrics = [row_to_dict(row) for row in conn.execute("SELECT * FROM metrics ORDER BY created_at DESC LIMIT 20")]
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

    def create_or_get_active_task(self, task_type: str, resource_type: str, resource_id: str, phase: str = "queued") -> tuple[dict[str, Any], bool]:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM task_runs
                WHERE task_type = ? AND resource_type = ? AND resource_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_type, resource_type, resource_id),
            ).fetchone()
            if row is not None:
                return _task_from_row(row), False
            task_id = new_id("task")
            created_at = utc_now()
            conn.execute(
                """
                INSERT INTO task_runs
                (id, task_type, resource_type, resource_id, status, phase, created_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?)
                """,
                (task_id, task_type, resource_type, resource_id, phase, created_at),
            )
            row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
            return _task_from_row(row), True

    def create_finished_task(
        self,
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
        status = "failed" if error_summary else "succeeded"
        created_at = utc_now()
        task_id = new_id("task")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO task_runs
                (id, task_type, resource_type, resource_id, status, phase, progress_current, progress_total, truncated, error_summary, result_ref, created_at, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
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

    def get_task(self, task_id: str) -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return _task_from_row(row)

    def list_tasks(
        self,
        status: str | None = None,
        task_type: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
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
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM task_runs {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def mark_task_running(self, task_id: str, phase: str = "running", progress_total: int | None = None) -> None:
        with connect() as conn:
            if progress_total is None:
                conn.execute(
                    "UPDATE task_runs SET status = 'running', phase = ?, started_at = COALESCE(started_at, ?) WHERE id = ?",
                    (phase, utc_now(), task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE task_runs
                    SET status = 'running', phase = ?, started_at = COALESCE(started_at, ?), progress_total = ?
                    WHERE id = ?
                    """,
                    (phase, utc_now(), progress_total, task_id),
                )

    def update_task_progress(
        self,
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
        params.append(task_id)
        with connect() as conn:
            conn.execute(f"UPDATE task_runs SET {', '.join(assignments)} WHERE id = ?", params)

    def succeed_task(self, task_id: str, *, result_ref: str | None = None, truncated: bool = False, phase: str = "completed") -> None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'succeeded', phase = ?, truncated = ?, result_ref = ?, error_summary = NULL, finished_at = ?
                WHERE id = ?
                """,
                (phase, 1 if truncated else 0, result_ref, utc_now(), task_id),
            )

    def fail_task(self, task_id: str, error_summary: str, phase: str = "failed") -> None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'failed', phase = ?, error_summary = ?, finished_at = ?
                WHERE id = ?
                """,
                (phase, error_summary, utc_now(), task_id),
            )

    def fail_stale_tasks(self, error_summary: str = "Task interrupted by application restart.") -> int:
        with connect() as conn:
            active = conn.execute("SELECT COUNT(*) AS count FROM task_runs WHERE status IN ('queued', 'running')").fetchone()["count"]
            if not active:
                return 0
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'failed', phase = 'failed', error_summary = ?, finished_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (error_summary, utc_now()),
            )
        return int(active)


state_store = RuntimeStateStore()
