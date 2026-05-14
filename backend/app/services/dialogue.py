from __future__ import annotations

from ..agents.dialogue import TeacherDialogueAgent
from ..db import connect, json_dumps, row_to_dict, utc_now
from ..schemas import DialogueResponse, IntegrationDecision
from ..utils.ids import new_id
from .integration import get_decisions, update_decision


def handle_message(message: str) -> DialogueResponse:
    decisions = [IntegrationDecision(**decision) for decision in get_decisions()]
    response = TeacherDialogueAgent().interpret(message, decisions)
    with connect() as conn:
        conn.execute(
            "INSERT INTO dialogue_messages (id, role, message, decision_id, created_at) VALUES (?, 'teacher', ?, ?, ?)",
            (new_id("msg"), message, response.updated_decision.id if response.updated_decision else None, utc_now()),
        )
        conn.execute(
            "INSERT INTO dialogue_messages (id, role, message, decision_id, created_at) VALUES (?, 'agent', ?, ?, ?)",
            (new_id("msg"), response.reply, response.updated_decision.id if response.updated_decision else None, utc_now()),
        )
    if response.updated_decision:
        update_decision(response.updated_decision.model_dump())
    return response


def list_messages() -> list[dict]:
    with connect() as conn:
        return [row_to_dict(row) for row in conn.execute("SELECT * FROM dialogue_messages ORDER BY created_at")]

