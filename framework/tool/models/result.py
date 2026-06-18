from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from framework.shared.result import ErrorDetail
from framework.shared.time import format_datetime
from framework.governance import GateCheckResult
from framework.tool.governance.redaction import contains_redacted_value, redact_sensitive_values
from framework.tool.models.artifact_ref import ArtifactRef
from framework.tool.models.status import ToolStatus


@dataclass(frozen=True)
class ToolPolicyTrace:
    tool_name: str
    allowed: bool
    risk_level: str = "unknown"
    requires_approval: bool = False
    approval_granted: bool | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_name", str(self.tool_name))
        object.__setattr__(self, "risk_level", str(self.risk_level or "unknown"))
        object.__setattr__(self, "allowed", bool(self.allowed))
        object.__setattr__(self, "requires_approval", bool(self.requires_approval))
        object.__setattr__(
            self,
            "checks",
            [_check_to_dict(check) for check in self.checks],
        )
        object.__setattr__(self, "reason", str(self.reason or ""))

    @classmethod
    def from_any(cls, value: Any) -> "ToolPolicyTrace | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(
                tool_name=str(value.get("tool_name") or ""),
                allowed=bool(value.get("allowed", False)),
                risk_level=str(value.get("risk_level") or "unknown"),
                requires_approval=bool(value.get("requires_approval", False)),
                approval_granted=(
                    bool(value["approval_granted"])
                    if value.get("approval_granted") is not None
                    else None
                ),
                checks=[
                    dict(item)
                    for item in value.get("checks", [])
                    if isinstance(item, dict)
                ],
                reason=str(value.get("reason") or ""),
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "approval_granted": self.approval_granted,
            "checks": [dict(check) for check in self.checks],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    output: Any = None
    output_summary: str | None = None
    artifact_refs: list[ArtifactRef] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    approval_id: str | None = None
    redacted: bool = True
    output_bytes: int | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    tool_name: str = ""
    artifacts: list[ArtifactRef] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    gate_result: dict[str, Any] | None = None
    redacted_output: Any = None
    policy_trace: ToolPolicyTrace | dict[str, Any] | None = None
    retry_count: int = 0
    timeout: bool = False
    trace_id: str | None = None
    span_id: str | None = None
    error_envelope: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        status = self.status if isinstance(self.status, ToolStatus) else ToolStatus(str(self.status))
        artifacts = list(self.artifacts or self.artifact_refs or [])
        artifact_refs = list(self.artifact_refs or self.artifacts or [])
        if artifacts and not artifact_refs:
            artifact_refs = artifacts
        if artifact_refs and not artifacts:
            artifacts = artifact_refs
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "artifact_refs", [ArtifactRef.from_any(ref) for ref in artifact_refs])
        object.__setattr__(self, "artifacts", [ArtifactRef.from_any(ref) for ref in artifacts])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        if self.gate_result is not None:
            object.__setattr__(self, "gate_result", dict(self.gate_result))
        object.__setattr__(
            self,
            "policy_trace",
            ToolPolicyTrace.from_any(self.policy_trace),
        )
        if self.redacted_output is None and self.output is not None:
            object.__setattr__(self, "redacted_output", redact_sensitive_values(self.output))
        elif self.redacted_output is not None:
            object.__setattr__(
                self,
                "redacted_output",
                redact_sensitive_values(self.redacted_output),
            )
        object.__setattr__(self, "retry_count", max(0, int(self.retry_count or 0)))
        object.__setattr__(self, "timeout", bool(self.timeout))
        if self.error_envelope is None:
            object.__setattr__(self, "error_envelope", _error_envelope(self))
        else:
            object.__setattr__(self, "error_envelope", dict(self.error_envelope))

    @classmethod
    def success(
        cls,
        tool_name: str,
        output: Any,
        *,
        call_id: str | None = None,
        artifacts: list[ArtifactRef] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolStatus.SUCCEEDED,
            output=output,
            artifacts=list(artifacts or []),
            artifact_refs=list(artifacts or []),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failure(
        cls,
        tool_name: str,
        error: Exception | ErrorDetail,
        *,
        call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        if isinstance(error, ErrorDetail):
            error_type = error.code
            error_message = error.message
        else:
            error_type = type(error).__name__
            error_message = str(error)
        return cls(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolStatus.FAILED,
            error_type=error_type,
            error_message=error_message,
            metadata=dict(metadata or {}),
        )

    @property
    def ok(self) -> bool:
        return self.status == ToolStatus.SUCCEEDED

    @property
    def error(self) -> dict[str, str | None] | ErrorDetail | None:
        if self.error_type is None and self.error_message is None:
            return None
        return {"type": self.error_type, "message": self.error_message}

    @property
    def artifact_ref(self) -> ArtifactRef | None:
        return self.artifact_refs[0] if self.artifact_refs else None

    @property
    def redaction_report(self) -> dict[str, Any]:
        return {
            "redacted": self.redacted,
            "contains_redacted_value": contains_redacted_value(redact_sensitive_values(self.output)),
        }

    def with_duration(self, duration_ms: float) -> "ToolResult":
        if self.duration_ms is not None:
            return self
        return replace(self, duration_ms=duration_ms)

    def to_dict(self) -> dict[str, Any]:
        policy_trace = ToolPolicyTrace.from_any(self.policy_trace)
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "output": redact_sensitive_values(self.output),
            "redacted_output": redact_sensitive_values(self.redacted_output),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "artifact_ref": self.artifact_ref.to_dict() if self.artifact_ref else None,
            "artifacts": [artifact_ref.to_dict() for artifact_ref in self.artifacts],
            "metadata": dict(self.metadata),
            "redaction_report": self.redaction_report,
            "output_summary": self.output_summary,
            "artifact_refs": [artifact_ref.to_dict() for artifact_ref in self.artifact_refs],
            "error_type": self.error_type,
            "error_message": self.error_message,
            "approval_id": self.approval_id,
            "redacted": self.redacted,
            "output_bytes": self.output_bytes,
            "started_at": format_datetime(self.started_at),
            "finished_at": format_datetime(self.finished_at),
            "gate_result": dict(self.gate_result) if self.gate_result is not None else None,
            "policy_trace": (
                policy_trace.to_dict() if policy_trace is not None else None
            ),
            "retry_count": self.retry_count,
            "timeout": self.timeout,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "error_envelope": (
                dict(self.error_envelope) if self.error_envelope is not None else None
            ),
        }


def _check_to_dict(check: Any) -> dict[str, Any]:
    if isinstance(check, GateCheckResult):
        return check.to_dict()
    if hasattr(check, "to_dict"):
        value = check.to_dict()
        return dict(value) if isinstance(value, dict) else {"value": value}
    if isinstance(check, dict):
        return dict(check)
    return {"value": str(check)}


def _error_envelope(result: ToolResult) -> dict[str, Any] | None:
    if result.error_type is None and result.error_message is None:
        return None
    error_type = result.error_type or "ToolRuntimeError"
    return {
        "error_code": error_type,
        "error_type": error_type,
        "message": result.error_message or "",
        "domain": "tool",
        "severity": "error",
        "retryable": result.status in {ToolStatus.TIMEOUT, ToolStatus.FAILED},
        "tool_call_id": result.call_id,
        "details": {
            "tool_name": result.tool_name,
            "status": result.status.value,
            "output_bytes": result.output_bytes,
        },
    }
