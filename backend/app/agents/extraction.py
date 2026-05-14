from __future__ import annotations

from ..schemas import KnowledgeEdge, KnowledgeNode
from ..services.llm import llm_client
from ..utils.ids import new_id
from ..utils.text import normalize_space, top_keywords


RELATION_TYPES = ["prerequisite", "parallel", "contains", "applies_to"]


class KnowledgeExtractionAgent:
    system_prompt = (
        "你是学科教材知识图谱抽取 Agent。只输出 JSON。"
        "节点字段为 name, definition, category, page, source_excerpt。"
        "边字段为 source_name, target_name, relation_type, description。"
        "relation_type 只能是 prerequisite, parallel, contains, applies_to。"
    )

    def extract(self, chapter: dict, textbook_id: str) -> tuple[list[KnowledgeNode], list[KnowledgeEdge], dict]:
        result = llm_client.complete_json(
            self.system_prompt,
            (
                f"教材章节: {chapter['title']}\n"
                f"起始页: {chapter['page_start']}\n"
                "请抽取 3-8 个核心知识点，以及它们之间最重要的关系。\n"
                f"正文:\n{chapter['content'][:6000]}"
            ),
        )
        if result.get("data"):
            try:
                return self._from_llm(result["data"], chapter, textbook_id, result)
            except Exception:
                pass
        nodes, edges = self._heuristic(chapter, textbook_id)
        return nodes, edges, {"elapsed_ms": result.elapsed_ms, "token_estimate": result.token_estimate, "fallback": True}

    def _from_llm(self, data: dict, chapter: dict, textbook_id: str, metrics: dict) -> tuple[list[KnowledgeNode], list[KnowledgeEdge], dict]:
        raw_nodes = data.get("nodes", [])
        raw_edges = data.get("edges", [])
        nodes: list[KnowledgeNode] = []
        name_to_id: dict[str, str] = {}
        for raw in raw_nodes[:10]:
            node_id = new_id("node")
            name = str(raw["name"]).strip()
            name_to_id[name] = node_id
            nodes.append(
                KnowledgeNode(
                    id=node_id,
                    textbook_id=textbook_id,
                    chapter_id=chapter["id"],
                    name=name,
                    definition=str(raw.get("definition", "")).strip()[:600],
                    category=str(raw.get("category", "核心概念")).strip() or "核心概念",
                    page=int(raw.get("page") or chapter["page_start"]),
                    source_excerpt=str(raw.get("source_excerpt", chapter["content"][:160])).strip()[:400],
                    metadata={"agent": "KnowledgeExtractionAgent"},
                )
            )
        edges: list[KnowledgeEdge] = []
        for raw in raw_edges[:16]:
            relation_type = raw.get("relation_type", "parallel")
            if relation_type not in RELATION_TYPES:
                relation_type = "parallel"
            source = name_to_id.get(str(raw.get("source_name", "")).strip())
            target = name_to_id.get(str(raw.get("target_name", "")).strip())
            if source and target and source != target:
                edges.append(
                    KnowledgeEdge(
                        id=new_id("edge"),
                        textbook_id=textbook_id,
                        source=source,
                        target=target,
                        relation_type=relation_type,
                        description=str(raw.get("description", ""))[:400],
                    )
                )
        return nodes, edges, {"elapsed_ms": metrics.elapsed_ms, "token_estimate": metrics.token_estimate, "fallback": False}

    def _heuristic(self, chapter: dict, textbook_id: str) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
        content = normalize_space(chapter["content"])
        keywords = top_keywords(content, limit=6)
        if not keywords:
            keywords = [chapter["title"]]
        nodes: list[KnowledgeNode] = []
        for index, keyword in enumerate(keywords[:6]):
            excerpt_start = max(content.find(keyword) - 40, 0) if keyword in content else 0
            excerpt = content[excerpt_start : excerpt_start + 180] or content[:180]
            nodes.append(
                KnowledgeNode(
                    id=new_id("node"),
                    textbook_id=textbook_id,
                    chapter_id=chapter["id"],
                    name=keyword,
                    definition=f"{keyword} 是《{chapter['title']}》中的核心知识点，需结合原文章节理解。",
                    category="核心概念" if index == 0 else "相关概念",
                    page=chapter["page_start"],
                    source_excerpt=excerpt,
                    metadata={"agent": "KnowledgeExtractionAgent", "fallback": True},
                )
            )
        edges: list[KnowledgeEdge] = []
        for index in range(len(nodes) - 1):
            relation_type = RELATION_TYPES[index % len(RELATION_TYPES)]
            edges.append(
                KnowledgeEdge(
                    id=new_id("edge"),
                    textbook_id=textbook_id,
                    source=nodes[index].id,
                    target=nodes[index + 1].id,
                    relation_type=relation_type,
                    description=f"{nodes[index].name} 与 {nodes[index + 1].name} 在章节中共同出现，存在教学关联。",
                )
            )
        return nodes, edges

