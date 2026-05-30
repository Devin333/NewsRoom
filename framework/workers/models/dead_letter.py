from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.shared.time import format_datetime
from framework.workers.models.task import Task, TaskError, TaskEvent
from framework.workers.models.status import TaskStatus


@dataclass(frozen=True)
class DeadLetterRecord:
    task: Task
    reason: str
    error: TaskError | None = None
    attempts: int | None = None
    failed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_event: TaskEvent | None = None

    @classmethod
    def from_task(cls, task: Task, error: str | TaskError | Exception) -> "DeadLetterRecord":
        if isinstance(error, TaskError):
            task_error = error
        elif isinstance(error, Exception):
            task_error = TaskError(type(error).__name__, str(error), retryable=False)
        else:
            task_error = TaskError("TaskFailed", str(error), retryable=False)
        task.status = TaskStatus.DEAD_LETTER
        return cls(task=task, reason=task_error.error_message, error=task_error, attempts=task.attempts)

    @property
    def created_at(self) -> datetime:
        return self.failed_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "reason": self.reason,
            "error": self.error.to_dict() if self.error else None,
            "attempts": self.task.attempts if self.attempts is None else self.attempts,
            "failed_at": format_datetime(self.failed_at),
            "last_event": self.last_event.to_dict() if self.last_event else None,
        }
