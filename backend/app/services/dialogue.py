from __future__ import annotations

from ..agents.dialogue import TeacherDialogueAgent
from ..runtime.store import state_store
from ..schemas import DialogueResponse, IntegrationDecision
from .integration import get_decisions, update_decision


def handle_message(message: str, workspace_id: str = "global") -> DialogueResponse:
    decisions = [IntegrationDecision(**decision) for decision in get_decisions(workspace_id=workspace_id)]
    response = TeacherDialogueAgent().interpret(message, decisions)
    decision_id = response.updated_decision.id if response.updated_decision else None
    state_store.append_dialogue_message(workspace_id, "teacher", message, decision_id)
    state_store.append_dialogue_message(workspace_id, "agent", response.reply, decision_id)
    if response.updated_decision:
        update_decision(response.updated_decision.model_dump(), workspace_id=workspace_id)
    return response


def list_messages(workspace_id: str = "global") -> list[dict]:
    return state_store.list_dialogue_messages(workspace_id)
