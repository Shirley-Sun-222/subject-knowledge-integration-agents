from __future__ import annotations

from fastapi import HTTPException

from ..agents.report import ReportAgent
from ..runtime.files import runtime_files
from ..runtime.tasks import TaskContext, task_runner


def enqueue_report_pdf_build(workspace_id: str = "global") -> tuple[dict, bool]:
    return task_runner.enqueue(
        workspace_id,
        "build_report_pdf",
        "report",
        "latest",
        lambda context: _build_report_pdf_task(context, workspace_id=workspace_id),
    )


def _build_report_pdf_task(context: TaskContext, workspace_id: str = "global") -> dict:
    context.start("rendering_pdf", progress_total=1)
    import asyncio

    path = asyncio.run(ReportAgent().generate_pdf(workspace_id=workspace_id))
    context.progress(phase="writing_pdf", progress_current=1, progress_total=1)
    return {
        "result_ref": str(path),
        "phase": "completed",
        "truncated": False,
    }


def get_report_markdown(workspace_id: str = "global") -> dict:
    return {"markdown": ReportAgent().render_markdown(workspace_id=workspace_id)}


async def get_report_pdf_path(workspace_id: str = "global"):
    path = runtime_files.report_pdf_path(workspace_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF report not built yet")
    return path
