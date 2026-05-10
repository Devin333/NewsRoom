from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class TaskStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class Task:
    task_type: str
    payload: dict[str, Any]
    queue_name: str = "news:queue:daily"
    task_id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.CREATED
    attempts: int = 0
    max_attempts: int = 3
    leased_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "queue_name": self.queue_name,
            "payload": dict(self.payload),
            "status": self.status.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "leased_by": self.leased_by,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True)
class TaskError:
    error_type: str
    error_message: str


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    success: bool
    status: TaskStatus
    workflow_run_id: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))
