from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable

from ..config import settings
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
    _last_phase: str | None = None
    _last_progress_current: int | None = None
    _last_progress_total: int | None = None
    _last_truncated: bool | None = None
    _last_metadata: dict[str, Any] | None = None
    _last_persisted_at: float = field(default_factory=monotonic)

    def start(self, phase: str, progress_total: int = 0) -> None:
        state_store.mark_task_running(self.workspace_id, self.task_id, phase=phase, progress_total=progress_total)
        self._last_phase = phase
        self._last_progress_total = progress_total
        self._last_persisted_at = monotonic()

    def progress(
        self,
        *,
        phase: str | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        truncated: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._should_persist_progress(
            phase=phase,
            progress_current=progress_current,
            progress_total=progress_total,
            truncated=truncated,
            metadata=metadata,
        ):
            return
        state_store.update_task_progress(
            self.workspace_id,
            self.task_id,
            phase=phase,
            progress_current=progress_current,
            progress_total=progress_total,
            truncated=truncated,
            metadata=metadata,
        )
        if phase is not None:
            self._last_phase = phase
        if progress_current is not None:
            self._last_progress_current = progress_current
        if progress_total is not None:
            self._last_progress_total = progress_total
        if truncated is not None:
            self._last_truncated = truncated
        if metadata is not None:
            self._last_metadata = metadata
        self._last_persisted_at = monotonic()

    def _should_persist_progress(
        self,
        *,
        phase: str | None,
        progress_current: int | None,
        progress_total: int | None,
        truncated: bool | None,
        metadata: dict[str, Any] | None,
    ) -> bool:
        if phase is not None and phase != self._last_phase:
            return True
        if progress_total is not None and progress_total != self._last_progress_total:
            return True
        if truncated is not None and truncated != self._last_truncated:
            return True
        if metadata is not None and metadata != self._last_metadata:
            return True
        if progress_current is None:
            return False

        previous = self._last_progress_current
        total = progress_total if progress_total is not None else self._last_progress_total
        if previous is None:
            return True
        if progress_current <= 2 or progress_current == previous:
            return progress_current != previous and (phase is not None or total is not None)
        if total and total > 0:
            if progress_current >= total:
                return True
            step = max(1, total // 25)
            if (progress_current - previous) >= step:
                return True
        return (monotonic() - self._last_persisted_at) >= settings.task_progress_write_interval_seconds


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
