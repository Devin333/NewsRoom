from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from framework.workers.models.result import TaskEnqueueResult
from framework.workers.models.task import Task


@dataclass(frozen=True)
class LeasedTask:
    queue_name: str
    message_id: str
    task: Task

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_name": self.queue_name,
            "message_id": self.message_id,
            "task": self.task.to_dict(),
        }


@dataclass(frozen=True)
class QueueStatus:
    queue_name: str
    pending_count: int = 0
    leased_count: int = 0
    delayed_count: int = 0
    dead_letter_count: int = 0
    lag: int | None = None
    oldest_task_age: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_name": self.queue_name,
            "pending_count": self.pending_count,
            "leased_count": self.leased_count,
            "delayed_count": self.delayed_count,
            "dead_letter_count": self.dead_letter_count,
            "lag": self.lag,
            "oldest_task_age": self.oldest_task_age,
            "metadata": dict(self.metadata),
        }


class TaskQueue(Protocol):
    def enqueue(self, task: Task) -> TaskEnqueueResult | str | None: ...

    def lease(
        self,
        queue: str,
        worker_id: str,
        lease_seconds: int,
        limit: int = 1,
    ) -> list[LeasedTask]: ...

    def ack(self, task_id: str) -> None: ...

    def nack(self, task_id: str, error: Exception | str, retry_at: datetime | None = None) -> None: ...

    def status(self, queue: str | None = None) -> QueueStatus: ...
