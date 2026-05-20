from __future__ import annotations

from dataclasses import dataclass

from framework.workers.models.result import TaskResult
from framework.workers.models.status import TaskStatus
from framework.workers.models.task import Task, TaskError
from framework.workers.registry.registry import TaskHandlerRegistry


@dataclass
class TaskDispatcher:
    registry: TaskHandlerRegistry

    def dispatch(self, task: Task) -> TaskResult:
        handler = self.registry.get(task.task_type)
        if handler is None:
            return TaskResult(
                task_id=task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type="UnknownTaskType",
                error_message=f"no handler for {task.task_type}",
            )
        try:
            return handler.handle(task)
        except Exception as exc:
            error = TaskError(type(exc).__name__, str(exc))
            return TaskResult(
                task_id=task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type=error.error_type,
                error_message=error.error_message,
            )
