from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared import RuntimeStatus
from framework.shared.json import to_jsonable as to_json_safe
from framework.shared.result import ErrorDetail
from framework.shared.time import format_datetime, utc_now
from framework.specs import StepStatus, WorkflowStatus
from framework.workflow.runtime.artifacts import ArtifactRef


@dataclass(frozen=True)
class WorkflowError:
    error_type: str
    message: str
    step_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "step_id": self.step_id,
            "details": to_json_safe(self.details),
        }


@dataclass(frozen=True)
class StepOutcome:
    status: StepStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    lineage: list[dict[str, Any]] = field(default_factory=list)
    next_hint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", StepStatus(self.status))

    @classmethod
    def success(cls, step_id: str, output: dict[str, Any] | None = None) -> "StepOutcome":
        _ = step_id
        return cls(status=StepStatus.SUCCEEDED, outputs=dict(output or {}))

    @classmethod
    def failure(cls, step_id: str, error: Exception | ErrorDetail) -> "StepOutcome":
        if isinstance(error, ErrorDetail):
            detail = error
        else:
            detail = ErrorDetail.from_exception(error)
        return cls(
            status=StepStatus.FAILED,
            error_type=detail.code,
            error_message=detail.message,
            error_details={**detail.details, "step_id": step_id},
        )

    @property
    def step_id(self) -> str | None:
        value = self.error_details.get("step_id")
        if value is None:
            return None
        return str(value)

    @property
    def output(self) -> dict[str, Any]:
        return self.outputs

    @property
    def error(self) -> ErrorDetail | None:
        if self.error_type is None and self.error_message is None:
            return None
        return ErrorDetail(
            code=self.error_type or "step_error",
            message=self.error_message or "",
            details=dict(self.error_details),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepOutcome":
        return cls(
            status=StepStatus(str(data["status"])),
            outputs=dict(data.get("outputs") or {}),
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
            error_details=dict(data.get("error_details") or {}),
            metrics=dict(data.get("metrics") or {}),
            artifacts=list(data.get("artifacts") or []),
            lineage=list(data.get("lineage") or []),
            next_hint=data.get("next_hint"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "outputs": to_json_safe(self.outputs),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_details": to_json_safe(self.error_details),
            "metrics": to_json_safe(self.metrics),
            "artifacts": to_json_safe(self.artifacts),
            "lineage": to_json_safe(self.lineage),
            "next_hint": self.next_hint,
        }


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: WorkflowError | None = None
    path: list[str] = field(default_factory=list)
    step_results: dict[str, StepOutcome] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", WorkflowStatus(self.status))

    @property
    def success(self) -> bool:
        return self.status == WorkflowStatus.SUCCEEDED

    @property
    def runtime_status(self) -> RuntimeStatus:
        return _workflow_runtime_status(self.status)

    def terminal_output(self) -> dict[str, Any]:
        return dict(self.output)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowResult":
        raw_error = data.get("error")
        if raw_error is None:
            error = None
        else:
            error = WorkflowError(
                error_type=str(raw_error["error_type"]),
                message=str(raw_error["message"]),
                step_id=raw_error.get("step_id"),
                details=dict(raw_error.get("details") or {}),
            )
        return cls(
            run_id=str(data["run_id"]),
            workflow_id=str(data["workflow_id"]),
            workflow_version=str(data["workflow_version"]),
            status=WorkflowStatus(str(data["status"])),
            output=dict(data.get("output") or {}),
            error=error,
            path=[str(step_id) for step_id in data.get("path", [])],
            step_results={
                str(step_id): StepOutcome.from_dict(raw_outcome)
                for step_id, raw_outcome in (data.get("step_results") or {}).items()
            },
            manifest=dict(data.get("manifest") or {}),
            artifact_dir=data.get("artifact_dir"),
            manifest_path=data.get("manifest_path"),
            events_path=data.get("events_path"),
            started_at=_optional_datetime(data.get("started_at")) or utc_now(),
            finished_at=_optional_datetime(data.get("finished_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status.value,
            "output": to_json_safe(self.output),
            "error": self.error.to_dict() if self.error else None,
            "path": list(self.path),
            "step_results": {
                step_id: outcome.to_dict() for step_id, outcome in self.step_results.items()
            },
            "manifest": to_json_safe(self.manifest),
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "events_path": self.events_path,
            "started_at": format_datetime(self.started_at),
            "finished_at": format_datetime(self.finished_at) if self.finished_at else None,
        }


def _workflow_runtime_status(status: WorkflowStatus) -> RuntimeStatus:
    mapping = {
        WorkflowStatus.CREATED: RuntimeStatus.PENDING,
        WorkflowStatus.DRAFT: RuntimeStatus.PENDING,
        WorkflowStatus.READY: RuntimeStatus.PENDING,
        WorkflowStatus.RUNNING: RuntimeStatus.RUNNING,
        WorkflowStatus.RETRYING: RuntimeStatus.RUNNING,
        WorkflowStatus.PAUSED: RuntimeStatus.PAUSED,
        WorkflowStatus.WAITING_FOR_HUMAN: RuntimeStatus.PAUSED,
        WorkflowStatus.SUCCEEDED: RuntimeStatus.SUCCEEDED,
        WorkflowStatus.FAILED: RuntimeStatus.FAILED,
        WorkflowStatus.BLOCKED: RuntimeStatus.FAILED,
        WorkflowStatus.CANCELLED: RuntimeStatus.CANCELLED,
        WorkflowStatus.BUDGET_EXCEEDED: RuntimeStatus.FAILED,
    }
    return mapping[status]


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    from framework.shared.time import parse_datetime

    return parse_datetime(str(value))



