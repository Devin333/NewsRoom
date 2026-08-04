from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from framework.shared.public_errors import ApprovedPublicError
from framework.workers.models.result import TaskEnqueueResult
from framework.workers.models.task import Task


@dataclass(frozen=True)
class LeasedTask:
    queue_name: str
    message_id: str
    task: Task
    owner_id: str | None = None
    lease_id: str | None = None
    fencing_token: int | None = None
    attempt: int | None = None
    lease_expires_at: datetime | None = None
    effect_key: str | None = None

    @property
    def is_fenced(self) -> bool:
        return bool(self.lease_id and self.fencing_token is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_name": self.queue_name,
            "message_id": self.message_id,
            "owner_id": self.owner_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "attempt": self.attempt,
            "lease_expires_at": (
                self.lease_expires_at.isoformat().replace("+00:00", "Z")
                if self.lease_expires_at is not None
                else None
            ),
            "effect_key": self.effect_key,
            "task": self.task.to_dict(),
        }


class StaleTaskLeaseError(ApprovedPublicError):
    """Raised when a worker no longer owns the fenced Redis task lease."""

    def __init__(self, leased: LeasedTask, *, operation: str) -> None:
        super().__init__(
            f"task lease is stale during {operation}",
            context="worker",
            error_type="StaleTaskLeaseError",
            error_message="task lease is stale",
        )
        self.task_id = leased.task.task_id
        self.queue_name = leased.queue_name
        self.message_id = leased.message_id
        self.lease_id = leased.lease_id
        self.owner_id = leased.owner_id
        self.fencing_token = leased.fencing_token
        self.operation = operation


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

    def lease(self, worker_id: str, queue_names: list[str]) -> Task | None: ...

    def ack(self, task_id: str, worker_id: str | None = None) -> None: ...

    def fail(self, task_id: str, worker_id: str, error: Any) -> None: ...

    def reclaim_stale(self, worker_id: str, queue_names: list[str]) -> Task | None: ...

    def status(self, queue: str | None = None) -> QueueStatus: ...
