from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4


class TaskStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PAUSED = "paused"


@dataclass
class Task:
    task_type: str
    payload: dict[str, Any]
    queue_name: str = "news:queue:daily"
    task_id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.CREATED
    attempts: int = 0
    max_attempts: int = 3
    priority: int = 0
    timeout_seconds: int | None = None
    dedup_key: str | None = None
    trace_id: str | None = None
    leased_by: str | None = None
    lease_expires_at: datetime | None = None
    scheduled_for: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def attempt(self) -> int:
        return self.attempts

    @attempt.setter
    def attempt(self, value: int) -> None:
        self.attempts = int(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "queue_name": self.queue_name,
            "payload": dict(self.payload),
            "status": self.status.value,
            "attempt": self.attempts,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "dedup_key": self.dedup_key,
            "trace_id": self.trace_id,
            "leased_by": self.leased_by,
            "lease_expires_at": _format_datetime(self.lease_expires_at),
            "scheduled_for": self.scheduled_for.isoformat().replace("+00:00", "Z")
            if self.scheduled_for
            else None,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        created_at = _parse_datetime(data.get("created_at"))
        scheduled_for = _parse_optional_datetime(data.get("scheduled_for"))
        return cls(
            task_id=str(data.get("task_id") or uuid4().hex),
            task_type=str(data["task_type"]),
            queue_name=str(data.get("queue_name") or "news:queue:daily"),
            payload=dict(data.get("payload") or {}),
            status=TaskStatus(data.get("status") or TaskStatus.CREATED.value),
            attempts=int(data.get("attempts", data.get("attempt", 0)) or 0),
            max_attempts=int(data.get("max_attempts") or 3),
            priority=int(data.get("priority") or 0),
            timeout_seconds=_optional_int(data.get("timeout_seconds")),
            dedup_key=data.get("dedup_key"),
            trace_id=data.get("trace_id"),
            leased_by=data.get("leased_by"),
            lease_expires_at=_parse_optional_datetime(data.get("lease_expires_at")),
            scheduled_for=scheduled_for,
            metadata=dict(data.get("metadata") or {}),
            created_at=created_at,
            updated_at=_parse_datetime(data.get("updated_at")),
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
class TaskEnqueueResult:
    task_id: str
    queue_name: str
    accepted: bool
    status: TaskStatus
    message_id: str | None = None
    reason: str | None = None
    delayed_until: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "queue_name": self.queue_name,
            "accepted": self.accepted,
            "status": self.status.value,
            "message_id": self.message_id,
            "reason": self.reason,
            "delayed_until": _format_datetime(self.delayed_until),
        }

    def __bool__(self) -> bool:
        return self.accepted

    def __str__(self) -> str:
        return self.message_id or self.task_id


@dataclass(frozen=True)
class BackpressurePolicy:
    max_pending_per_queue: int | None = None

    def should_reject(self, *, pending_count: int) -> bool:
        return (
            self.max_pending_per_queue is not None
            and pending_count >= self.max_pending_per_queue
        )

    def to_dict(self) -> dict[str, Any]:
        return {"max_pending_per_queue": self.max_pending_per_queue}


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


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    success: bool
    status: TaskStatus
    workflow_run_id: str | None = None
    task_status: TaskStatus | None = None
    run_status: str | None = None
    report_status: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", TaskStatus(self.status))
        task_status = self.task_status if self.task_status is not None else self.status
        object.__setattr__(self, "task_status", TaskStatus(task_status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "status": self.status.value,
            "task_status": self.task_status.value,
            "run_status": self.run_status,
            "report_status": self.report_status,
            "workflow_run_id": self.workflow_run_id,
            "output": dict(self.output),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "finished_at": _format_datetime(self.finished_at),
        }


@dataclass(frozen=True)
class LeasedTask:
    queue_name: str
    message_id: str
    task: Task


@dataclass(frozen=True)
class TaskRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 30
    max_delay_seconds: int = 900
    backoff_multiplier: float = 2.0
    retryable_error_types: list[str] = field(default_factory=list)
    non_retryable_error_types: list[str] = field(default_factory=list)

    def should_retry(self, task: Task, error: TaskError) -> bool:
        if error.error_type in self.non_retryable_error_types:
            return False
        if self.retryable_error_types and error.error_type not in self.retryable_error_types:
            return False
        return error.retryable and task.attempts < min(task.max_attempts, self.max_attempts)

    def next_run_at(
        self,
        task: Task,
        *,
        now: datetime | None = None,
    ) -> datetime:
        reference = _normalize_datetime(now or datetime.now(UTC))
        return reference + timedelta(seconds=self.delay_seconds(task.attempts))

    def delay_seconds(self, attempts: int) -> int:
        delay = self.base_delay_seconds * (self.backoff_multiplier ** max(0, attempts - 1))
        return min(self.max_delay_seconds, int(delay))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "retryable_error_types": list(self.retryable_error_types),
            "non_retryable_error_types": list(self.non_retryable_error_types),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "task_id": self.task_id,
            "task_status": self.task_status.value,
            "worker_id": self.worker_id,
            "queue_name": self.queue_name,
            "payload": dict(self.payload),
            "occurred_at": _format_datetime(self.occurred_at),
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

    @classmethod
    def from_task(cls, task: Task, *, workflow_run_id: str | None = None) -> TaskRecord:
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "queue_name": self.queue_name,
            "status": self.status.value,
            "payload": dict(self.payload),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "workflow_run_id": self.workflow_run_id,
            "error": dict(self.error) if self.error else None,
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
            "metadata": dict(self.metadata),
        }


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
            "last_heartbeat_at": _format_datetime(self.last_heartbeat_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorkerMetrics:
    queued_count: int = 0
    leased_count: int = 0
    running_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    dead_letter_count: int = 0
    cancelled_count: int = 0
    pending_count: int = 0
    lag: int | None = None
    oldest_task_age: float | None = None
    avg_task_latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queued_count": self.queued_count,
            "leased_count": self.leased_count,
            "running_count": self.running_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "dead_letter_count": self.dead_letter_count,
            "cancelled_count": self.cancelled_count,
            "pending_count": self.pending_count,
            "lag": self.lag,
            "oldest_task_age": self.oldest_task_age,
            "avg_task_latency_ms": self.avg_task_latency_ms,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DeadLetterRecord:
    task: Task
    reason: str
    error: TaskError | None = None
    attempts: int | None = None
    failed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_event: TaskEvent | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "reason": self.reason,
            "error": self.error.to_dict() if self.error else None,
            "attempts": self.task.attempts if self.attempts is None else self.attempts,
            "failed_at": _format_datetime(self.failed_at),
            "last_event": self.last_event.to_dict() if self.last_event else None,
        }

    @property
    def created_at(self) -> datetime:
        return self.failed_at


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(UTC)


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return _parse_datetime(value)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value).isoformat().replace("+00:00", "Z")


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
