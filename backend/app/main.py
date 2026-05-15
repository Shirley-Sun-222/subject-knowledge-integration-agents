from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .runtime.store import state_store
from .runtime.tasks import task_runner
from .schemas import DialogueRequest, RagQueryRequest, TaskDetail, TaskSummary
from .services import dialogue, graph, integration, rag, reporting, textbooks


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
    task_runner.startup()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/textbooks/upload", status_code=202)
async def upload_textbooks(files: list[UploadFile] = File(...)) -> dict:
    uploaded = []
    for file in files:
        textbook = await textbooks.save_upload(file)
        task, _ = textbooks.enqueue_parse_textbook(textbook["id"])
        uploaded.append({"textbook": textbook, "task": _task_summary(task)})
    return {"uploads": uploaded}


@app.get("/api/textbooks")
def list_textbooks() -> dict:
    return {"textbooks": textbooks.list_textbooks()}


@app.post("/api/graphs/build", status_code=202)
def build_graph(payload: dict) -> dict:
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(status_code=400, detail="textbook_id is required")
    max_chapters = payload.get("max_chapters")
    if max_chapters is not None:
        try:
            max_chapters = int(max_chapters)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="max_chapters must be an integer") from exc
        if max_chapters <= 0:
            raise HTTPException(status_code=400, detail="max_chapters must be greater than 0")
    task, _ = graph.enqueue_build_graph(textbook_id, max_chapters=max_chapters)
    return {"task": _task_summary(task)}


@app.get("/api/graphs/{textbook_id}")
def get_graph(textbook_id: str) -> dict:
    return graph.get_graph(textbook_id)


@app.post("/api/integration/run", status_code=202)
def run_integration() -> dict:
    task, _ = integration.enqueue_integration()
    return {"task": _task_summary(task)}


@app.get("/api/integration")
def get_integration() -> dict:
    return integration.get_integration()


@app.post("/api/rag/index", status_code=202)
def build_rag_index() -> dict:
    task, _ = rag.enqueue_build_index()
    return {"task": _task_summary(task)}


@app.get("/api/rag/status")
def rag_status() -> dict:
    return rag.status()


@app.post("/api/rag/query")
def rag_query(request: RagQueryRequest) -> dict:
    return rag.query(request.question, request.top_k).model_dump()


@app.post("/api/dialogue/message")
def dialogue_message(request: DialogueRequest) -> dict:
    return dialogue.handle_message(request.message).model_dump()


@app.get("/api/dialogue/messages")
def dialogue_messages() -> dict:
    return {"messages": dialogue.list_messages()}


@app.get("/api/report/integration")
def integration_report() -> dict:
    return reporting.get_report_markdown()


@app.post("/api/report/pdf/build", status_code=202)
def integration_report_pdf_build() -> dict:
    task, _ = reporting.enqueue_report_pdf_build()
    return {"task": _task_summary(task)}


@app.get("/api/report/pdf")
async def integration_report_pdf() -> FileResponse:
    path = await reporting.get_report_pdf_path()
    return FileResponse(path, media_type="application/pdf", filename="整合报告.pdf")


@app.get("/api/tasks")
def list_tasks(status: str | None = None, task_type: str | None = None, resource_type: str | None = None, resource_id: str | None = None) -> dict:
    tasks = state_store.list_tasks(status=status, task_type=task_type, resource_type=resource_type, resource_id=resource_id)
    return {"tasks": [_task_detail(task) for task in tasks]}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    try:
        task = state_store.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    return {"task": _task_detail(task)}


if settings.frontend_dist and settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")


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
