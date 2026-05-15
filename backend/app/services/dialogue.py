from __future__ import annotations

from ..agents.dialogue import TeacherDialogueAgent
from ..runtime.store import state_store
from ..schemas import DialogueResponse, IntegrationDecision
from .integration import get_decisions, update_decision


def handle_message(message: str) -> DialogueResponse:
    decisions = [IntegrationDecision(**decision) for decision in get_decisions()]
    response = TeacherDialogueAgent().interpret(message, decisions)
    decision_id = response.updated_decision.id if response.updated_decision else None
    state_store.append_dialogue_message("teacher", message, decision_id)
    state_store.append_dialogue_message("agent", response.reply, decision_id)
    if response.updated_decision:
        update_decision(response.updated_decision.model_dump())
    return response


def list_messages() -> list[dict]:
    return state_store.list_dialogue_messages()
