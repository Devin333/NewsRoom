from __future__ import annotations

from core.framework.workers.handlers import DailyIntelligenceTaskHandler
from core.framework.workers.in_memory import InMemoryTaskQueue
from core.framework.workers.models import TaskError, TaskResult


class WorkerLoop:
    def __init__(
        self,
        *,
        worker_id: str,
        queue: InMemoryTaskQueue,
        handlers: dict[str, DailyIntelligenceTaskHandler],
        queue_names: list[str],
    ) -> None:
        self.worker_id = worker_id
        self.queue = queue
        self.handlers = handlers
        self.queue_names = queue_names

    def run_once(self) -> TaskResult | None:
        task = self.queue.lease(self.worker_id, self.queue_names)
        if task is None:
            return None
        handler = self.handlers.get(task.task_type)
        if handler is None:
            error = TaskError("UnknownTaskType", f"no handler for {task.task_type}")
            self.queue.fail(task.task_id, self.worker_id, error)
            return None
        try:
            result = handler.handle(task)
        except Exception as exc:
            self.queue.fail(task.task_id, self.worker_id, TaskError(type(exc).__name__, str(exc)))
            raise
        if result.success:
            self.queue.ack(task.task_id, self.worker_id)
        else:
            self.queue.fail(
                task.task_id,
                self.worker_id,
                TaskError(result.error_type or "TaskFailed", result.error_message or "task failed"),
            )
        return result
