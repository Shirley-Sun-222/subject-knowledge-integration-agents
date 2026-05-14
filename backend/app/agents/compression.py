from __future__ import annotations

from ..db import utc_now
from ..schemas import IntegrationDecision
from ..utils.ids import new_id


class CompressionPlannerAgent:
    def plan(self, groups: list[list[dict]], original_chars: int) -> tuple[list[IntegrationDecision], dict]:
        decisions: list[IntegrationDecision] = []
        retained_chars = 0
        for group in groups:
            if len(group) > 1:
                representative = max(group, key=lambda node: len(node["definition"]) + len(node["source_excerpt"]))
                affected = [node["id"] for node in group]
                retained_chars += min(len(representative["definition"]) + len(representative["source_excerpt"]), 420)
                decisions.append(
                    IntegrationDecision(
                        id=new_id("merge"),
                        action="merge",
                        affected_nodes=affected,
                        result_node=representative["id"],
                        reason=f"{len(group)} 本教材出现语义相近知识点，保留 '{representative['name']}' 作为整合代表。",
                        confidence=0.86,
                        created_at=utc_now(),
                    )
                )
            else:
                node = group[0]
                retained_chars += min(len(node["definition"]) + len(node["source_excerpt"]), 360)
                decisions.append(
                    IntegrationDecision(
                        id=new_id("keep"),
                        action="keep",
                        affected_nodes=[node["id"]],
                        result_node=node["id"],
                        reason=f"'{node['name']}' 当前未发现跨教材重复，保留作为唯一知识点。",
                        confidence=0.78,
                        created_at=utc_now(),
                    )
                )

        target_chars = max(int(original_chars * 0.3), 1)
        if retained_chars > target_chars:
            overflow = retained_chars - target_chars
            removable = [decision for decision in decisions if decision.action == "keep"]
            for decision in removable:
                if overflow <= 0:
                    break
                decision.action = "remove"
                decision.reason = f"{decision.reason} 为满足 30% 精华压缩目标，暂标记为低优先级冗余项，可由教师反馈恢复。"
                decision.confidence = 0.62
                overflow -= 260
            retained_chars = min(retained_chars, target_chars)

        stats = {
            "original_chars": original_chars,
            "integrated_chars": retained_chars,
            "compression_ratio": retained_chars / original_chars if original_chars else 0,
        }
        return decisions, stats

