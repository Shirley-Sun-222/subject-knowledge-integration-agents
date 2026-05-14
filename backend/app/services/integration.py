from __future__ import annotations

from collections import Counter

from ..agents.alignment import AlignmentAgent
from ..agents.compression import CompressionPlannerAgent
from ..db import connect, json_dumps, json_loads, row_to_dict
from .graph import get_all_graph_nodes


def run_integration() -> dict:
    nodes = get_all_graph_nodes()
    with connect() as conn:
        original_chars = conn.execute("SELECT COALESCE(SUM(total_chars), 0) AS total FROM textbooks").fetchone()["total"]
    groups = AlignmentAgent().group_nodes(nodes)
    decisions, stats = CompressionPlannerAgent().plan(groups, original_chars)
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
    return get_integration(stats)


def get_decisions() -> list[dict]:
    with connect() as conn:
        decisions = [row_to_dict(row) for row in conn.execute("SELECT * FROM integration_decisions ORDER BY created_at")]
    for decision in decisions:
        decision["affected_nodes"] = json_loads(decision["affected_nodes"], [])
    return decisions


def update_decision(decision: dict) -> None:
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


def get_integration(stats: dict | None = None) -> dict:
    nodes = get_all_graph_nodes()
    by_id = {node["id"]: node for node in nodes}
    decisions = get_decisions()
    integrated_nodes = []
    removed = set()
    for decision in decisions:
        if decision["action"] == "remove":
            removed.update(decision["affected_nodes"])
            continue
        result_id = decision.get("result_node") or decision["affected_nodes"][0]
        representative = by_id.get(result_id)
        if representative:
            source_nodes = [by_id[node_id] for node_id in decision["affected_nodes"] if node_id in by_id]
            textbook_titles = sorted({node["textbook_title"] for node in source_nodes})
            integrated_nodes.append(
                {
                    **representative,
                    "id": result_id,
                    "frequency": len(source_nodes),
                    "sources": textbook_titles,
                    "decision_id": decision["id"],
                    "decision_action": decision["action"],
                    "decision_reason": decision["reason"],
                }
            )
    source_ids = {node["id"] for node in integrated_nodes}
    with connect() as conn:
        edges = [row_to_dict(row) for row in conn.execute("SELECT * FROM knowledge_edges")]
        original_chars = conn.execute("SELECT COALESCE(SUM(total_chars), 0) AS total FROM textbooks").fetchone()["total"]
    filtered_edges = [edge for edge in edges if edge["source"] in source_ids and edge["target"] in source_ids]
    if stats is None:
        kept_chars = sum(min(len(node["definition"]) + len(node["source_excerpt"]), 420) for node in integrated_nodes)
        stats = {
            "original_chars": original_chars,
            "integrated_chars": kept_chars,
            "compression_ratio": kept_chars / original_chars if original_chars else 0,
        }
    action_counts = Counter(decision["action"] for decision in decisions)
    return {
        "nodes": integrated_nodes,
        "edges": filtered_edges,
        "decisions": decisions,
        "removed_node_ids": sorted(removed),
        "stats": {**stats, "decision_counts": dict(action_counts), "node_count": len(integrated_nodes), "edge_count": len(filtered_edges)},
    }

