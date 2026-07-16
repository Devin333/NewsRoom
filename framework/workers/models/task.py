from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from uuid import uuid4

from framework.events.propagation import normalize_trace_carrier
from framework.shared.time import ensure_utc, format_datetime, parse_datetime
from framework.workers.models.status import TaskStatus


DEFAULT_TASK_QUEUE = "framework:queue:default"


@dataclass
class Task:
    task_type: str
    payload: dict[str, Any]
    queue_name: str = DEFAULT_TASK_QUEUE
    task_id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.CREATED
    attempts: int = 0
    max_attempts: int = 3
    priority: int = 0
    timeout_seconds: int | None = None
    dedup_key: str | None = None
    trace_id: str | None = None
    trace_carrier: dict[str, str] = field(default_factory=dict)
    leased_by: str | None = None
    lease_expires_at: datetime | None = None
    scheduled_for: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.trace_carrier = _bounded_trace_carrier(self.trace_carrier)

    @property
    def queue(self) -> str:
        return self.queue_name

    @queue.setter
    def queue(self, value: str) -> None:
        self.queue_name = value

    @property
    def run_at(self) -> datetime | None:
        return self.scheduled_for

    @run_at.setter
    def run_at(self, value: datetime | None) -> None:
        self.scheduled_for = ensure_utc(value) if value is not None else None

    @property
    def attempt(self) -> int:
        return self.attempts

    @attempt.setter
    def attempt(self, value: int) -> None:
        self.attempts = int(value)

    def with_attempt(self, attempt: int) -> "Task":
        clone = Task.from_dict(self.to_dict())
        clone.attempts = int(attempt)
        return clone

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "queue": self.queue_name,
            "queue_name": self.queue_name,
            "payload": dict(self.payload),
            "status": TaskStatus(self.status).value,
            "attempt": self.attempts,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "dedup_key": self.dedup_key,
            "trace_id": self.trace_id,
            "trace_carrier": dict(self.trace_carrier),
            "leased_by": self.leased_by,
            "lease_expires_at": format_datetime(self.lease_expires_at),
            "run_at": format_datetime(self.scheduled_for),
            "scheduled_for": format_datetime(self.scheduled_for),
            "metadata": dict(self.metadata),
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            task_id=str(data.get("task_id") or uuid4().hex),
            task_type=str(data["task_type"]),
            queue_name=str(data.get("queue_name") or data.get("queue") or DEFAULT_TASK_QUEUE),
            payload=dict(data.get("payload") or {}),
            status=TaskStatus(data.get("status") or TaskStatus.CREATED.value),
            attempts=int(data.get("attempts", data.get("attempt", 0)) or 0),
            max_attempts=int(data.get("max_attempts") or 3),
            priority=int(data.get("priority") or 0),
            timeout_seconds=_optional_int(data.get("timeout_seconds")),
            dedup_key=data.get("dedup_key"),
            trace_id=data.get("trace_id"),
            trace_carrier=dict(data.get("trace_carrier") or {}),
            leased_by=data.get("leased_by"),
            lease_expires_at=parse_datetime(data.get("lease_expires_at")),
            scheduled_for=parse_datetime(data.get("scheduled_for") or data.get("run_at")),
            metadata=dict(data.get("metadata") or {}),
            created_at=parse_datetime(data.get("created_at")) or datetime.now(UTC),
            updated_at=parse_datetime(data.get("updated_at")) or datetime.now(UTC),
        )


@dataclass(frozen=True)
class TaskError:
    error_type: str
    error_message: str
    retryable: bool = True
    operator_action_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "operator_action_required": self.operator_action_required,
        }


@dataclass(frozen=True)
class TaskEvent:
    event_type: str
    task_id: str
    task_status: TaskStatus | str
    worker_id: str | None = None
    queue_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_status", TaskStatus(self.task_status))
        occurred_at = (
            parse_datetime(self.occurred_at)
            if not isinstance(self.occurred_at, datetime)
            else ensure_utc(self.occurred_at)
        )
        object.__setattr__(self, "occurred_at", occurred_at or datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "task_id": self.task_id,
            "task_status": TaskStatus(self.task_status).value,
            "worker_id": self.worker_id,
            "queue_name": self.queue_name,
            "payload": dict(self.payload),
            "occurred_at": format_datetime(self.occurred_at),
        }


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    task_type: str
    queue_name: str
    status: TaskStatus | str
    payload: dict[str, Any]
    attempts: int = 0
    max_attempts: int = 3
    worker_id: str | None = None
    workflow_run_id: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", TaskStatus(self.status))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))

    @classmethod
    def from_task(cls, task: Task, *, workflow_run_id: str | None = None) -> "TaskRecord":
        return cls(
            task_id=task.task_id,
            task_type=task.task_type,
            queue_name=task.queue_name,
            status=task.status,
            payload=dict(task.payload),
            attempts=task.attempts,
            max_attempts=task.max_attempts,
            worker_id=task.leased_by,
            workflow_run_id=workflow_run_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
            metadata=dict(task.metadata),
        )

    def mark_leased(self, worker_id: str, lease_until: datetime | None = None) -> "TaskRecord":
        metadata = dict(self.metadata)
        if lease_until is not None:
            metadata["lease_until"] = format_datetime(lease_until)
        return self._replace(status=TaskStatus.LEASED, worker_id=worker_id, metadata=metadata)

    def mark_completed(self, result: Any) -> "TaskRecord":
        metadata = dict(self.metadata)
        to_dict = getattr(result, "to_dict", None)
        metadata["result"] = to_dict() if callable(to_dict) else result
        return self._replace(status=TaskStatus.SUCCEEDED, metadata=metadata)

    def mark_failed(self, error: Any) -> "TaskRecord":
        if isinstance(error, TaskError):
            error_payload = error.to_dict()
        elif isinstance(error, dict):
            error_payload = dict(error)
        else:
            error_payload = {"error_type": type(error).__name__, "error_message": str(error)}
        return self._replace(status=TaskStatus.FAILED, error=error_payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "queue_name": self.queue_name,
            "queue": self.queue_name,
            "status": TaskStatus(self.status).value,
            "payload": dict(self.payload),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "workflow_run_id": self.workflow_run_id,
            "error": dict(self.error) if self.error else None,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
            "metadata": dict(self.metadata),
        }

    def _replace(self, **changes: Any) -> "TaskRecord":
        payload = self.to_dict()
        payload.update(changes)
        payload["updated_at"] = datetime.now(UTC)
        return TaskRecord(
            task_id=payload["task_id"],
            task_type=payload["task_type"],
            queue_name=payload["queue_name"],
            status=payload["status"],
            payload=payload["payload"],
            attempts=payload["attempts"],
            max_attempts=payload["max_attempts"],
            worker_id=payload.get("worker_id"),
            workflow_run_id=payload.get("workflow_run_id"),
            error=payload.get("error"),
            created_at=parse_datetime(payload.get("created_at")) or datetime.now(UTC),
            updated_at=parse_datetime(payload.get("updated_at")) or datetime.now(UTC),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True)
class WorkerRecord:
    worker_id: str
    queue_names: list[str]
    status: str
    current_task_id: str | None = None
    processed_count: int = 0
    failed_count: int = 0
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "queue_names": list(self.queue_names),
            "status": self.status,
            "current_task_id": self.current_task_id,
            "processed_count": self.processed_count,
            "failed_count": self.failed_count,
            "last_heartbeat_at": format_datetime(self.last_heartbeat_at),
            "metadata": dict(self.metadata),
        }


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _bounded_trace_carrier(value: Any) -> dict[str, str]:
    return dict(normalize_trace_carrier(value))
