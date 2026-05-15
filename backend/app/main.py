from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .runtime.session import ensure_workspace_id
from .runtime.store import state_store
from .runtime.tasks import task_runner
from .schemas import DialogueRequest, RagQueryRequest, SessionLlmConfigRequest, SessionLlmConfigStatus, SessionWorkspaceStatus, TaskDetail, TaskSummary
from .services import dialogue, graph, integration, rag, reporting, textbooks
from .services.llm import llm_client


app = FastAPI(title="学科知识整合智能体", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    state_store.clear_legacy_global_state()
    task_runner.startup()
    state_store.purge_expired_workspaces()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/textbooks/upload", status_code=202)
async def upload_textbooks(request: Request, response: Response, files: list[UploadFile] = File(...)) -> dict:
    workspace_id = _workspace(request, response)
    uploaded = []
    for file in files:
        textbook = await textbooks.save_upload(file, workspace_id=workspace_id)
        task, _ = textbooks.enqueue_parse_textbook(textbook["id"], workspace_id=workspace_id)
        uploaded.append({"textbook": textbook, "task": _task_summary(task)})
    return {"uploads": uploaded}


@app.get("/api/textbooks")
def list_textbooks(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return {"textbooks": textbooks.list_textbooks(workspace_id=workspace_id)}


@app.delete("/api/textbooks/{textbook_id}")
def delete_textbook(textbook_id: str, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    try:
        textbooks.delete_textbook(textbook_id, workspace_id=workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="textbook not found") from exc
    return {"deleted": textbook_id}


@app.post("/api/graphs/build", status_code=202)
def build_graph(payload: dict, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(status_code=400, detail="textbook_id is required")
    mode = payload.get("mode", "preview")
    max_chapters = payload.get("max_chapters")
    if mode == "full":
        max_chapters = None
    elif max_chapters is not None:
        try:
            max_chapters = int(max_chapters)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="max_chapters must be an integer") from exc
        if max_chapters <= 0:
            raise HTTPException(status_code=400, detail="max_chapters must be greater than 0")
    task, _ = graph.enqueue_build_graph(textbook_id, max_chapters=max_chapters, workspace_id=workspace_id)
    return {"task": _task_summary(task)}


@app.get("/api/graphs/{textbook_id}")
def get_graph(textbook_id: str, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return graph.get_graph(textbook_id, workspace_id=workspace_id)


@app.post("/api/integration/run", status_code=202)
def run_integration(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    task, _ = integration.enqueue_integration(workspace_id=workspace_id)
    return {"task": _task_summary(task)}


@app.get("/api/integration")
def get_integration(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return integration.get_integration(workspace_id=workspace_id)


@app.post("/api/rag/index", status_code=202)
def build_rag_index(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    task, _ = rag.enqueue_build_index(workspace_id=workspace_id)
    return {"task": _task_summary(task)}


@app.get("/api/rag/status")
def rag_status(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return rag.status(workspace_id=workspace_id)


@app.post("/api/rag/query")
def rag_query(body: RagQueryRequest, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return rag.query(body.question, body.top_k, workspace_id=workspace_id).model_dump()


@app.post("/api/dialogue/message")
def dialogue_message(body: DialogueRequest, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return dialogue.handle_message(body.message, workspace_id=workspace_id).model_dump()


@app.get("/api/dialogue/messages")
def dialogue_messages(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return {"messages": dialogue.list_messages(workspace_id=workspace_id)}


@app.get("/api/report/integration")
def integration_report(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    return reporting.get_report_markdown(workspace_id=workspace_id)


@app.post("/api/report/pdf/build", status_code=202)
def integration_report_pdf_build(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    task, _ = reporting.enqueue_report_pdf_build(workspace_id=workspace_id)
    return {"task": _task_summary(task)}


@app.get("/api/report/pdf")
async def integration_report_pdf(request: Request, response: Response) -> FileResponse:
    workspace_id = _workspace(request, response)
    path = await reporting.get_report_pdf_path(workspace_id=workspace_id)
    return FileResponse(path, media_type="application/pdf", filename="整合报告.pdf")


@app.get("/api/tasks")
def list_tasks(request: Request, response: Response, status: str | None = None, task_type: str | None = None, resource_type: str | None = None, resource_id: str | None = None) -> dict:
    workspace_id = _workspace(request, response)
    tasks = state_store.list_tasks(workspace_id, status=status, task_type=task_type, resource_type=resource_type, resource_id=resource_id)
    return {"tasks": [_task_detail(task) for task in tasks]}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    try:
        task = state_store.get_task(workspace_id, task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    return {"task": _task_detail(task)}


@app.post("/api/session/llm-config")
def set_session_llm_config(body: SessionLlmConfigRequest, request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    state_store.set_workspace_llm_config(workspace_id, body.base_url, body.api_key.get_secret_value(), body.model)
    return {"configured": True}


@app.get("/api/session/llm-config/status")
def session_llm_config_status(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    resolved = llm_client.resolve_config(workspace_id)
    if resolved is None:
        status = SessionLlmConfigStatus(configured=False, source="none")
    else:
        status = SessionLlmConfigStatus(
            configured=True,
            source=resolved.source,
            model=resolved.model,
            base_url=resolved.base_url,
        )
    return {"status": status.model_dump()}


@app.delete("/api/session/llm-config")
def delete_session_llm_config(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    state_store.delete_workspace_llm_config(workspace_id)
    return {"configured": False}


@app.get("/api/session/workspace")
def session_workspace_status(request: Request, response: Response) -> dict:
    workspace_id = _workspace(request, response)
    status = SessionWorkspaceStatus(
        workspace_id=workspace_id,
        ttl_seconds=settings.session_workspace_ttl_seconds,
    )
    return {"workspace": status.model_dump()}


if settings.frontend_dist and settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")


def _workspace(request: Request, response: Response) -> str:
    state_store.purge_expired_workspaces()
    workspace_id = ensure_workspace_id(request, response)
    state_store.ensure_workspace(workspace_id)
    return workspace_id


def _task_summary(task: dict) -> dict:
    return TaskSummary(
        id=task["id"],
        task_type=task["task_type"],
        resource_type=task["resource_type"],
        resource_id=task["resource_id"],
        status=task["status"],
        phase=task["phase"],
    ).model_dump()


def _task_detail(task: dict) -> dict:
    return TaskDetail(
        id=task["id"],
        task_type=task["task_type"],
        resource_type=task["resource_type"],
        resource_id=task["resource_id"],
        status=task["status"],
        phase=task["phase"],
        progress_current=task.get("progress_current", 0),
        progress_total=task.get("progress_total", 0),
        truncated=bool(task.get("truncated", False)),
        error_summary=task.get("error_summary"),
        result_ref=task.get("result_ref"),
        created_at=task["created_at"],
        started_at=task.get("started_at"),
        finished_at=task.get("finished_at"),
    ).model_dump()
