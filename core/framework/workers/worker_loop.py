from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from core.framework.workers.handlers import DailyIntelligenceTaskHandler
from core.framework.workers.in_memory import InMemoryTaskQueue
from core.framework.workers.models import TaskError, TaskEvent, TaskResult, TaskStatus


@dataclass(frozen=True)
class WorkerLoopRunResult:
    worker_id: str
    iterations: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    idle_count: int
    stop_reason: str
    last_result: TaskResult | None = None

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "iterations": self.iterations,
            "processed_count": self.processed_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "idle_count": self.idle_count,
            "stop_reason": self.stop_reason,
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }


class WorkerLoop:
    def __init__(
        self,
        *,
        worker_id: str,
        queue: InMemoryTaskQueue,
        handlers: dict[str, DailyIntelligenceTaskHandler],
        queue_names: list[str],
        idle_sleep_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.queue = queue
        self.handlers = handlers
        self.queue_names = queue_names
        self.idle_sleep_seconds = idle_sleep_seconds
        self.sleep_fn = sleep_fn or time.sleep
        self.events: list[TaskEvent] = []

    def run(
        self,
        *,
        max_tasks: int | None = None,
        max_idle_polls: int | None = None,
        idle_sleep_seconds: float | None = None,
    ) -> WorkerLoopRunResult:
        if max_tasks is not None and max_tasks <= 0:
            raise ValueError("max_tasks must be greater than zero")
        if max_idle_polls is not None and max_idle_polls <= 0:
            raise ValueError("max_idle_polls must be greater than zero")
        sleep_seconds = self.idle_sleep_seconds if idle_sleep_seconds is None else idle_sleep_seconds
        if sleep_seconds < 0:
            raise ValueError("idle_sleep_seconds must be non-negative")

        iterations = 0
        processed_count = 0
        succeeded_count = 0
        failed_count = 0
        idle_count = 0
        last_result: TaskResult | None = None

        while True:
            result = self.run_once()
            iterations += 1
            last_result = result
            if result is None:
                idle_count += 1
                if max_idle_polls is not None and idle_count >= max_idle_polls:
                    return WorkerLoopRunResult(
                        worker_id=self.worker_id,
                        iterations=iterations,
                        processed_count=processed_count,
                        succeeded_count=succeeded_count,
                        failed_count=failed_count,
                        idle_count=idle_count,
                        stop_reason="max_idle_polls",
                        last_result=last_result,
                    )
                if sleep_seconds:
                    self.sleep_fn(sleep_seconds)
                continue

            processed_count += 1
            if result.success:
                succeeded_count += 1
            else:
                failed_count += 1
            if max_tasks is not None and processed_count >= max_tasks:
                return WorkerLoopRunResult(
                    worker_id=self.worker_id,
                    iterations=iterations,
                    processed_count=processed_count,
                    succeeded_count=succeeded_count,
                    failed_count=failed_count,
                    idle_count=idle_count,
                    stop_reason="max_tasks",
                    last_result=last_result,
                )

    def run_once(self) -> TaskResult | None:
        task = self.queue.lease(self.worker_id, self.queue_names)
        if task is None:
            return None
        task.status = TaskStatus.RUNNING
        self._record_event("task_started", task)
        handler = self.handlers.get(task.task_type)
        if handler is None:
            error = TaskError("UnknownTaskType", f"no handler for {task.task_type}")
            self.queue.fail(task.task_id, self.worker_id, error)
            self._record_event("task_failed", task, payload=error.to_dict())
            return TaskResult(
                task_id=task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type=error.error_type,
                error_message=error.error_message,
            )
        try:
            result = handler.handle(task)
        except Exception as exc:
            error = TaskError(type(exc).__name__, str(exc))
            self.queue.fail(task.task_id, self.worker_id, error)
            self._record_event("task_failed", task, payload=error.to_dict())
            return TaskResult(
                task_id=task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type=error.error_type,
                error_message=error.error_message,
            )
        if result.success and result.status == TaskStatus.SUCCEEDED:
            self.queue.ack(task.task_id, self.worker_id)
            self._record_event("task_succeeded", task)
        elif result.success and result.status in {TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.PAUSED}:
            task.status = result.status
            self._record_event("task_paused", task)
        elif result.success:
            task.status = result.status
            self._record_event("task_completed", task)
        else:
            self.queue.fail(
                task.task_id,
                self.worker_id,
                TaskError(result.error_type or "TaskFailed", result.error_message or "task failed"),
            )
            self._record_event(
                "task_failed",
                task,
                payload={"error_type": result.error_type, "error_message": result.error_message},
            )
        return result

    def _record_event(self, event_type: str, task, *, payload: dict | None = None) -> None:
        self.events.append(
            TaskEvent(
                event_type=event_type,
                task_id=task.task_id,
                task_status=task.status,
                worker_id=self.worker_id,
                queue_name=task.queue_name,
                payload=payload or {},
            )
        )
