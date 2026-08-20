from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.shared.time import format_datetime
from framework.shared.graph_identity import GraphIdentity, coerce_graph_identity
from framework.workers.models.execution_scope import WorkerExecutionScope
from framework.workers.models.status import TaskStatus


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
            "queue": self.queue_name,
            "accepted": self.accepted,
            "status": self.status.value,
            "message_id": self.message_id,
            "reason": self.reason,
            "delayed_until": format_datetime(self.delayed_until),
        }

    def __bool__(self) -> bool:
        return self.accepted

    def __str__(self) -> str:
        return self.message_id or self.task_id


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    success: bool
    status: TaskStatus
    retryable: bool = True
    graph_identity: GraphIdentity | None = None
    execution_scope: WorkerExecutionScope | str | None = None
    task_status: TaskStatus | None = None
    run_status: str | None = None
    report_status: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    error_id: str | None = None
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", TaskStatus(self.status))
        if self.graph_identity is not None:
            object.__setattr__(
                self,
                "graph_identity",
                coerce_graph_identity(self.graph_identity),
            )
        scope = self.execution_scope
        if scope is None and self.graph_identity is not None:
            scope = WorkerExecutionScope.GRAPH
        elif scope is not None:
            scope = WorkerExecutionScope(scope)
        object.__setattr__(self, "execution_scope", scope)
        if self.execution_scope is WorkerExecutionScope.STANDALONE and self.graph_identity is not None:
            raise ValueError("standalone worker results cannot carry Graph identity")
        task_status = self.task_status if self.task_status is not None else self.status
        object.__setattr__(self, "task_status", TaskStatus(task_status))

    def to_dict(self) -> dict[str, Any]:
        task_status = self.task_status or self.status
        return {
            "task_id": self.task_id,
            "success": self.success,
            "retryable": self.retryable,
            "status": self.status.value,
            "task_status": task_status.value,
            "run_status": self.run_status,
            "report_status": self.report_status,
            "graph_identity": (
                self.graph_identity.to_dict() if self.graph_identity is not None else None
            ),
            "execution_scope": (
                self.execution_scope.value if self.execution_scope is not None else None
            ),
            "output": dict(self.output),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_id": self.error_id,
            "finished_at": format_datetime(self.finished_at),
        }


def _task_result_success(
    cls,
    task_id: str,
    output: dict[str, Any] | None = None,
    *,
    graph_identity: GraphIdentity | None = None,
    execution_scope: WorkerExecutionScope | str | None = None,
) -> TaskResult:
    return cls(
        task_id=task_id,
        success=True,
        status=TaskStatus.SUCCEEDED,
        graph_identity=graph_identity,
        execution_scope=execution_scope,
        output=dict(output or {}),
    )


def _task_result_failure(
    cls,
    task_id: str,
    error: str | Exception,
    *,
    graph_identity: GraphIdentity | None = None,
    execution_scope: WorkerExecutionScope | str | None = None,
) -> TaskResult:
    if isinstance(error, Exception):
        error_type = type(error).__name__
        error_message = str(error)
    else:
        error_type = "TaskFailed"
        error_message = str(error)
    return cls(
        task_id=task_id,
        success=False,
        status=TaskStatus.FAILED,
        graph_identity=graph_identity,
        execution_scope=execution_scope,
        error_type=error_type,
        error_message=error_message,
    )


TaskResult.success = classmethod(_task_result_success)  # type: ignore[attr-defined]
TaskResult.failure = classmethod(_task_result_failure)  # type: ignore[attr-defined]
