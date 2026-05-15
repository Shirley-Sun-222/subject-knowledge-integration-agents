from __future__ import annotations

from collections import Counter

from ..agents.alignment import AlignmentAgent
from ..agents.compression import CompressionPlannerAgent
from ..runtime.store import state_store
from ..runtime.tasks import TaskContext, task_runner
from .graph import get_all_graph_nodes


def enqueue_integration() -> tuple[dict, bool]:
    return task_runner.enqueue(
        "run_integration",
        "system",
        "global",
        _run_integration_task,
    )


def _run_integration_task(context: TaskContext) -> dict:
    context.start("aligning_nodes", progress_total=1)
    result = run_integration(progress=context)
    return {
        "result_ref": "integration:global",
        "phase": "completed",
        "truncated": False,
    }


def run_integration(progress: TaskContext | None = None) -> dict:
    nodes = get_all_graph_nodes()
    original_chars = state_store.original_chars()
    groups = AlignmentAgent().group_nodes(nodes)
    if progress is not None:
        progress.progress(phase="planning_compression", progress_current=0, progress_total=1)
    decisions, stats = CompressionPlannerAgent().plan(groups, original_chars)
    state_store.replace_integration_decisions(decisions)
    if progress is not None:
        progress.progress(phase="writing_integration", progress_current=1, progress_total=1)
    return get_integration(stats)


def get_decisions() -> list[dict]:
    return state_store.list_integration_decisions()


def update_decision(decision: dict) -> None:
    state_store.update_integration_decision(decision)


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
    all_edges = state_store.list_all_graph_edges()
    filtered_edges = [edge for edge in all_edges if edge["source"] in source_ids and edge["target"] in source_ids]
    original_chars = state_store.original_chars()
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
