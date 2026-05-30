from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc

from framework.shared.time import ensure_utc
from framework.workers.models.task import Task, TaskError


@dataclass(frozen=True)
class TaskRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 30
    max_delay_seconds: int = 900
    backoff_multiplier: float = 2.0
    retryable_error_types: list[str] = field(default_factory=list)
    non_retryable_error_types: list[str] = field(default_factory=list)

    def should_retry(self, task: Task | int, error: TaskError | Exception | str | None = None) -> bool:
        if isinstance(task, int):
            return task < self.max_attempts
        task_error = _coerce_error(error)
        if task_error.error_type in self.non_retryable_error_types:
            return False
        if self.retryable_error_types and task_error.error_type not in self.retryable_error_types:
            return False
        return task_error.retryable and task.attempts < min(task.max_attempts, self.max_attempts)

    def next_run_at(
        self,
        task: Task,
        *,
        now: datetime | None = None,
    ) -> datetime:
        reference = ensure_utc(now or datetime.now(UTC))
        return reference + timedelta(seconds=self.delay_seconds(task.attempts))

    def delay_for_attempt(self, attempt: int) -> float:
        return float(self.delay_seconds(attempt))

    def delay_seconds(self, attempts: int) -> int:
        delay = self.base_delay_seconds * (self.backoff_multiplier ** max(0, attempts - 1))
        return min(self.max_delay_seconds, int(delay))

    def to_dict(self) -> dict:
        return {
            "max_attempts": self.max_attempts,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "retryable_error_types": list(self.retryable_error_types),
            "non_retryable_error_types": list(self.non_retryable_error_types),
        }


def _coerce_error(error: TaskError | Exception | str | None) -> TaskError:
    if isinstance(error, TaskError):
        return error
    if isinstance(error, Exception):
        return TaskError(type(error).__name__, str(error))
    return TaskError("TaskFailed", str(error or "task failed"))
