from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Callable

from .store import state_store


logger = logging.getLogger(__name__)
TaskHandler = Callable[["TaskContext"], dict[str, Any] | None]


def summarize_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return message[:240]


@dataclass
class TaskContext:
    workspace_id: str
    task_id: str

    def start(self, phase: str, progress_total: int = 0) -> None:
        state_store.mark_task_running(self.workspace_id, self.task_id, phase=phase, progress_total=progress_total)

    def progress(
        self,
        *,
        phase: str | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        truncated: bool | None = None,
    ) -> None:
        state_store.update_task_progress(
            self.workspace_id,
            self.task_id,
            phase=phase,
            progress_current=progress_current,
            progress_total=progress_total,
            truncated=truncated,
        )


class TaskRunner:
    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="runtime-task")
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    def startup(self) -> None:
        state_store.fail_stale_tasks()
        state_store.purge_expired_workspaces()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def enqueue(self, workspace_id: str, task_type: str, resource_type: str, resource_id: str, handler: TaskHandler) -> tuple[dict[str, Any], bool]:
        with self._lock:
            task, created = state_store.create_or_get_active_task(workspace_id, task_type, resource_type, resource_id)
            if not created:
                return task, False
            future = self._executor.submit(self._run_task, workspace_id, task["id"], handler)
            self._futures[task["id"]] = future
            return task, True

    def _run_task(self, workspace_id: str, task_id: str, handler: TaskHandler) -> None:
        context = TaskContext(workspace_id=workspace_id, task_id=task_id)
        try:
            result = handler(context) or {}
            state_store.succeed_task(
                workspace_id,
                task_id,
                result_ref=result.get("result_ref"),
                truncated=bool(result.get("truncated", False)),
                phase=str(result.get("phase", "completed")),
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.exception("Background task %s failed", task_id)
            state_store.fail_task(workspace_id, task_id, summarize_error(exc))
        finally:
            with self._lock:
                self._futures.pop(task_id, None)

    def wait_for(self, workspace_id: str, task_id: str, timeout: float = 10.0) -> dict[str, Any]:
        future = self._futures.get(task_id)
        if future is not None:
            future.result(timeout=timeout)
        return state_store.get_task(workspace_id, task_id)


task_runner = TaskRunner()
