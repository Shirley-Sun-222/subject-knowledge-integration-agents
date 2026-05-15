from __future__ import annotations

from fastapi import Request, Response

from ..utils.ids import new_id


SESSION_COOKIE = "session_workspace_id"


def ensure_workspace_id(request: Request, response: Response) -> str:
    workspace_id = request.cookies.get(SESSION_COOKIE)
    if workspace_id:
        return workspace_id
    workspace_id = new_id("ws")
    response.set_cookie(
        SESSION_COOKIE,
        workspace_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return workspace_id
