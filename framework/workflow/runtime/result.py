from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared import RuntimeStatus
from framework.shared.json import to_jsonable as to_json_safe
from framework.shared.result import ErrorDetail
from framework.shared.time import format_datetime, utc_now
from framework.specs import StepStatus, WorkflowStatus
from framework.artifacts import ArtifactRef


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


def framework_error_envelope(
    *,
    error_type: str | None,
    message: str | None,
    domain: str,
    retryable: bool = False,
    run_id: str | None = None,
    step_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if error_type is None and message is None:
        return None
    actual_type = error_type or f"{domain}_error"
    envelope: dict[str, Any] = {
        "error_code": actual_type,
        "error_type": actual_type,
        "message": message or "",
        "domain": domain,
        "severity": "error",
        "retryable": retryable,
        "details": to_json_safe(details or {}),
    }
    if run_id is not None:
        envelope["run_id"] = run_id
    if step_id is not None:
        envelope["step_id"] = step_id
    return envelope


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
    step_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[Any] = field(default_factory=list)
    evidence_refs: list[Any] = field(default_factory=list)
    gate_result: dict[str, Any] | None = None
    checkpoint_ref: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | float | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error_envelope: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", StepStatus(self.status))
        object.__setattr__(self, "outputs", dict(self.outputs))
        object.__setattr__(self, "error_details", dict(self.error_details))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "artifacts", list(self.artifacts))
        object.__setattr__(self, "lineage", [dict(item) for item in self.lineage])
        object.__setattr__(self, "trace_events", [dict(item) for item in self.trace_events])
        object.__setattr__(self, "artifact_refs", list(self.artifact_refs or self.artifacts))
        object.__setattr__(self, "evidence_refs", list(self.evidence_refs))
        object.__setattr__(self, "warnings", [str(item) for item in self.warnings])
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.step_id is None and self.error_details.get("step_id") is not None:
            object.__setattr__(self, "step_id", str(self.error_details["step_id"]))
        if self.step_id is not None and "step_id" not in self.error_details:
            object.__setattr__(
                self,
                "error_details",
                {**self.error_details, "step_id": self.step_id},
            )
        started_at = _optional_datetime(self.started_at)
        completed_at = _optional_datetime(self.completed_at)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        if self.duration_ms is None and started_at is not None and completed_at is not None:
            elapsed = completed_at - started_at
            object.__setattr__(self, "duration_ms", round(elapsed.total_seconds() * 1000, 3))
        if self.duration_ms is not None:
            metrics = dict(self.metrics)
            metrics.setdefault("duration_ms", self.duration_ms)
            object.__setattr__(self, "metrics", metrics)
        if self.error_envelope is None:
            object.__setattr__(
                self,
                "error_envelope",
                framework_error_envelope(
                    error_type=self.error_type,
                    message=self.error_message,
                    domain="workflow.step",
                    step_id=self.step_id,
                    details=self.error_details,
                ),
            )
        else:
            object.__setattr__(self, "error_envelope", dict(self.error_envelope))

    @classmethod
    def success(cls, step_id: str, output: dict[str, Any] | None = None) -> "StepOutcome":
        return cls(status=StepStatus.SUCCEEDED, outputs=dict(output or {}), step_id=step_id)

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
            step_id=step_id,
        )

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

    @property
    def standard_error(self) -> dict[str, Any] | None:
        return self.error_envelope_dict

    @property
    def error_envelope_dict(self) -> dict[str, Any] | None:
        if self.error_envelope is None:
            return None
        return dict(self.error_envelope)

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
            step_id=data.get("step_id"),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            trace_events=list(data.get("trace_events") or []),
            artifact_refs=list(data.get("artifact_refs") or []),
            evidence_refs=list(data.get("evidence_refs") or []),
            gate_result=dict(data["gate_result"]) if isinstance(data.get("gate_result"), dict) else None,
            checkpoint_ref=data.get("checkpoint_ref"),
            started_at=_optional_datetime(data.get("started_at")),
            completed_at=_optional_datetime(data.get("completed_at")),
            duration_ms=data.get("duration_ms"),
            warnings=list(data.get("warnings") or []),
            metadata=dict(data.get("metadata") or {}),
            error_envelope=(
                dict(data["error_envelope"])
                if isinstance(data.get("error_envelope"), dict)
                else None
            ),
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
            "step_id": self.step_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "trace_events": to_json_safe(self.trace_events),
            "artifact_refs": to_json_safe(self.artifact_refs),
            "evidence_refs": to_json_safe(self.evidence_refs),
            "gate_result": to_json_safe(self.gate_result),
            "checkpoint_ref": self.checkpoint_ref,
            "started_at": format_datetime(self.started_at),
            "completed_at": format_datetime(self.completed_at),
            "duration_ms": self.duration_ms,
            "warnings": to_json_safe(self.warnings),
            "metadata": to_json_safe(self.metadata),
            "error_envelope": to_json_safe(self.error_envelope),
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
    outputs: dict[str, Any] | None = None
    step_outcomes: list[StepOutcome] = field(default_factory=list)
    trace_id: str | None = None
    trace_ref: str | None = None
    manifest_ref: str | None = None
    checkpoint_ref: str | None = None
    gate_result: dict[str, Any] | None = None
    evaluation_summary: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_envelope: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", WorkflowStatus(self.status))
        output = dict(self.output)
        if self.outputs is not None and not output:
            output = dict(self.outputs)
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "outputs", dict(self.outputs or output))
        if not self.step_outcomes and self.step_results:
            object.__setattr__(self, "step_results", dict(self.step_results))
            object.__setattr__(self, "step_outcomes", list(self.step_results.values()))
        else:
            step_outcomes = list(self.step_outcomes)
            object.__setattr__(self, "step_outcomes", step_outcomes)
            step_results = dict(self.step_results)
            if not step_results:
                step_results = {
                    str(outcome.step_id): outcome
                    for outcome in step_outcomes
                    if outcome.step_id is not None
                }
            object.__setattr__(self, "step_results", step_results)
        object.__setattr__(self, "manifest", dict(self.manifest))
        object.__setattr__(self, "path", list(self.path))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "artifacts", list(self.artifacts))
        object.__setattr__(self, "warnings", [str(item) for item in self.warnings])
        object.__setattr__(self, "started_at", _optional_datetime(self.started_at) or utc_now())
        object.__setattr__(self, "finished_at", _optional_datetime(self.finished_at))
        if self.manifest_ref is None and self.manifest_path is not None:
            object.__setattr__(self, "manifest_ref", self.manifest_path)
        if self.trace_ref is None and self.events_path is not None:
            object.__setattr__(self, "trace_ref", self.events_path)
        if self.error_envelope is None and self.error is not None:
            object.__setattr__(
                self,
                "error_envelope",
                framework_error_envelope(
                    error_type=self.error.error_type,
                    message=self.error.message,
                    domain="workflow",
                    run_id=self.run_id,
                    step_id=self.error.step_id,
                    details=self.error.details,
                ),
            )
        elif self.error_envelope is not None:
            object.__setattr__(self, "error_envelope", dict(self.error_envelope))

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
            outputs=dict(data.get("outputs") or data.get("output") or {}),
            error=error,
            path=[str(step_id) for step_id in data.get("path", [])],
            step_results={
                str(step_id): StepOutcome.from_dict(raw_outcome)
                for step_id, raw_outcome in (data.get("step_results") or {}).items()
            },
            step_outcomes=[
                StepOutcome.from_dict(raw_outcome)
                for raw_outcome in data.get("step_outcomes") or []
            ],
            manifest=dict(data.get("manifest") or {}),
            artifact_dir=data.get("artifact_dir"),
            manifest_path=data.get("manifest_path"),
            events_path=data.get("events_path"),
            started_at=_optional_datetime(data.get("started_at")) or utc_now(),
            finished_at=_optional_datetime(data.get("finished_at")),
            trace_id=data.get("trace_id"),
            trace_ref=data.get("trace_ref"),
            manifest_ref=data.get("manifest_ref"),
            checkpoint_ref=data.get("checkpoint_ref"),
            gate_result=dict(data["gate_result"]) if isinstance(data.get("gate_result"), dict) else None,
            evaluation_summary=(
                dict(data["evaluation_summary"])
                if isinstance(data.get("evaluation_summary"), dict)
                else None
            ),
            metrics=dict(data.get("metrics") or {}),
            artifacts=list(data.get("artifacts") or []),
            warnings=list(data.get("warnings") or []),
            error_envelope=(
                dict(data["error_envelope"])
                if isinstance(data.get("error_envelope"), dict)
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status.value,
            "output": to_json_safe(self.output),
            "outputs": to_json_safe(self.outputs),
            "error": self.error.to_dict() if self.error else None,
            "path": list(self.path),
            "step_results": {
                step_id: outcome.to_dict() for step_id, outcome in self.step_results.items()
            },
            "step_outcomes": [outcome.to_dict() for outcome in self.step_outcomes],
            "manifest": to_json_safe(self.manifest),
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "events_path": self.events_path,
            "started_at": format_datetime(self.started_at),
            "finished_at": format_datetime(self.finished_at) if self.finished_at else None,
            "trace_id": self.trace_id,
            "trace_ref": self.trace_ref,
            "manifest_ref": self.manifest_ref,
            "checkpoint_ref": self.checkpoint_ref,
            "gate_result": to_json_safe(self.gate_result),
            "evaluation_summary": to_json_safe(self.evaluation_summary),
            "metrics": to_json_safe(self.metrics),
            "artifacts": to_json_safe(self.artifacts),
            "warnings": to_json_safe(self.warnings),
            "error_envelope": to_json_safe(self.error_envelope),
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



