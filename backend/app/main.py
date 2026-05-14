from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agents.report import ReportAgent
from .config import settings
from .db import init_db
from .schemas import DialogueRequest, RagQueryRequest
from .services import dialogue, graph, integration, rag, textbooks


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


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/textbooks/upload")
async def upload_textbooks(files: list[UploadFile] = File(...)) -> dict:
    uploaded = []
    for file in files:
        uploaded.append(await textbooks.save_and_parse_upload(file))
    return {"textbooks": uploaded}


@app.get("/api/textbooks")
def list_textbooks() -> dict:
    return {"textbooks": textbooks.list_textbooks()}


@app.post("/api/graphs/build")
def build_graph(payload: dict) -> dict:
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(status_code=400, detail="textbook_id is required")
    return graph.build_graph(textbook_id)


@app.get("/api/graphs/{textbook_id}")
def get_graph(textbook_id: str) -> dict:
    return graph.get_graph(textbook_id)


@app.post("/api/integration/run")
def run_integration() -> dict:
    return integration.run_integration()


@app.get("/api/integration")
def get_integration() -> dict:
    return integration.get_integration()


@app.post("/api/rag/index")
def build_rag_index() -> dict:
    return rag.build_index()


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
    report = ReportAgent().generate_markdown()
    return {"markdown": report}


@app.get("/api/report/pdf")
async def integration_report_pdf() -> FileResponse:
    path = await ReportAgent().generate_pdf()
    return FileResponse(path, media_type="application/pdf", filename="整合报告.pdf")


if settings.frontend_dist and settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")

