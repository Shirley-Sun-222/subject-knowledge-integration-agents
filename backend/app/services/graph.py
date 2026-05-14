from __future__ import annotations

from ..agents.extraction import KnowledgeExtractionAgent
from ..db import connect, json_dumps, json_loads, row_to_dict


def build_graph(textbook_id: str) -> dict:
    agent = KnowledgeExtractionAgent()
    total_tokens = 0
    total_elapsed = 0
    with connect() as conn:
        chapters = [row_to_dict(row) for row in conn.execute("SELECT * FROM chapters WHERE textbook_id = ? ORDER BY position", (textbook_id,))]
        conn.execute("DELETE FROM knowledge_edges WHERE textbook_id = ?", (textbook_id,))
        conn.execute("DELETE FROM knowledge_nodes WHERE textbook_id = ?", (textbook_id,))
        for chapter in chapters:
            nodes, edges, metrics = agent.extract(chapter, textbook_id)
            total_tokens += int(metrics.get("token_estimate", 0))
            total_elapsed += int(metrics.get("elapsed_ms", 0))
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
    graph = get_graph(textbook_id)
    graph["metrics"] = {"token_estimate": total_tokens, "elapsed_ms": total_elapsed}
    return graph


def get_graph(textbook_id: str) -> dict:
    with connect() as conn:
        nodes = [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_nodes WHERE textbook_id = ?", (textbook_id,))]
        for node in nodes:
            node["metadata"] = json_loads(node.get("metadata"), {})
        edges = [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_edges WHERE textbook_id = ?", (textbook_id,))]
        textbook = conn.execute("SELECT id, title, filename FROM textbooks WHERE id = ?", (textbook_id,)).fetchone()
        return {
            "textbook": row_to_dict(textbook) if textbook else None,
            "nodes": nodes,
            "edges": edges,
        }


def get_all_graph_nodes() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT n.*, t.title AS textbook_title, c.title AS chapter_title
            FROM knowledge_nodes n
            JOIN textbooks t ON t.id = n.textbook_id
            JOIN chapters c ON c.id = n.chapter_id
            """
        )
        nodes = [row_to_dict(row) for row in rows]
        for node in nodes:
            node["metadata"] = json_loads(node.get("metadata"), {})
        return nodes

