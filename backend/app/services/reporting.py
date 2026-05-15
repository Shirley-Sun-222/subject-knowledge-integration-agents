from __future__ import annotations

from fastapi import HTTPException

from ..agents.report import ReportAgent
from ..runtime.files import runtime_files
from ..runtime.tasks import TaskContext, task_runner


def enqueue_report_pdf_build() -> tuple[dict, bool]:
    return task_runner.enqueue(
        "build_report_pdf",
        "report",
        "latest",
        _build_report_pdf_task,
    )


def _build_report_pdf_task(context: TaskContext) -> dict:
    context.start("rendering_pdf", progress_total=1)
    import asyncio

    path = asyncio.run(ReportAgent().generate_pdf())
    context.progress(phase="writing_pdf", progress_current=1, progress_total=1)
    return {
        "result_ref": str(path),
        "phase": "completed",
        "truncated": False,
    }


def get_report_markdown() -> dict:
    return {"markdown": ReportAgent().render_markdown()}


async def get_report_pdf_path():
    path = runtime_files.report_pdf_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF report not built yet")
    return path
