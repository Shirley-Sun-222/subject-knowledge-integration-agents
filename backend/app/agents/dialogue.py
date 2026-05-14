from __future__ import annotations

from ..schemas import DialogueResponse, IntegrationDecision


class TeacherDialogueAgent:
    def interpret(self, message: str, decisions: list[IntegrationDecision]) -> DialogueResponse:
        target = _find_target_decision(message, decisions)
        if target is None:
            return DialogueResponse(
                reply="我已记录反馈。请指出具体知识点名称，系统会据此修改对应整合决策。",
                updated_decision=None,
                graph_updated=False,
            )
        text = message.lower()
        if "保留" in message or "不要删除" in message or "恢复" in message:
            target.action = "keep"
            target.reason = f"教师反馈要求保留该知识点。原决策已调整，并保留可追踪理由。"
        elif "删除" in message or "冗余" in message:
            target.action = "remove"
            target.reason = f"教师反馈认为该知识点冗余。系统已将其标记为删除。"
        elif "分开" in message or "不是同一个" in message or "拆分" in message:
            target.action = "keep"
            target.affected_nodes = target.affected_nodes[:1]
            target.reason = "教师反馈指出这些概念不应合并。系统已拆分并保留代表知识点。"
        elif "合并" in message or "一样" in message or "同一个" in message:
            target.action = "merge"
            target.reason = "教师反馈确认这些知识点可合并。系统已保留合并决策。"
        elif "why" in text or "为什么" in message:
            return DialogueResponse(
                reply=f"该决策理由：{target.reason} 置信度 {target.confidence:.2f}。",
                updated_decision=target,
                graph_updated=False,
            )
        else:
            return DialogueResponse(
                reply="反馈已记录，但没有识别到保留、删除、合并或拆分意图。请补充具体操作。",
                updated_decision=None,
                graph_updated=False,
            )
        target.confidence = max(target.confidence, 0.9)
        return DialogueResponse(reply=f"已根据教师反馈更新决策：{target.action}。", updated_decision=target, graph_updated=True)


def _find_target_decision(message: str, decisions: list[IntegrationDecision]) -> IntegrationDecision | None:
    if not decisions:
        return None
    lowered = message.lower()
    for decision in decisions:
        if decision.id.lower() in lowered:
            return decision
    return min(decisions, key=lambda item: item.confidence)

