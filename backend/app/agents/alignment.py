from __future__ import annotations

from collections import defaultdict

from ..services.embedding import embedding_service
from ..services.llm import llm_client
from ..utils.text import normalize_space


class AlignmentAgent:
    system_prompt = (
        "你是跨教材知识点语义对齐 Agent。只输出 JSON，格式为 "
        '{"equivalent": true/false, "reason": "...", "confidence": 0.0}'
        "。判断同义概念时要区分上下位概念、应用场景和近义但不等价的术语。"
    )

    def group_nodes(self, nodes: list[dict], threshold: float = 0.78) -> list[list[dict]]:
        if not nodes:
            return []
        vectors = embedding_service.embed([_node_text(node) for node in nodes])
        visited: set[int] = set()
        groups: list[list[dict]] = []
        for i, node in enumerate(nodes):
            if i in visited:
                continue
            group = [node]
            visited.add(i)
            for j in range(i + 1, len(nodes)):
                if j in visited or nodes[j]["textbook_id"] == node["textbook_id"]:
                    continue
                score = _cosine_vectors(vectors[i], vectors[j])
                if score >= threshold and self._llm_equivalent(node, nodes[j], score):
                    group.append(nodes[j])
                    visited.add(j)
            groups.append(group)
        return groups

    def _llm_equivalent(self, left: dict, right: dict, score: float) -> bool:
        if score >= 0.91:
            return True
        result = llm_client.complete_json(
            self.system_prompt,
            (
                "判断两个知识点是否表示同一学科概念。\n"
                f"A: {left['name']} - {left['definition']}\n"
                f"B: {right['name']} - {right['definition']}\n"
                f"embedding_similarity: {score:.3f}"
            ),
        )
        data = result.get("data")
        if not data:
            return score >= 0.84 and _normalized_name(left["name"]) == _normalized_name(right["name"])
        return bool(data.get("equivalent")) and float(data.get("confidence", score)) >= 0.68


def _node_text(node: dict) -> str:
    return f"{node['name']}。{node['definition']}。{node.get('source_excerpt', '')}"


def _normalized_name(name: str) -> str:
    return normalize_space(name).lower().replace(" ", "")


def _cosine_vectors(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

