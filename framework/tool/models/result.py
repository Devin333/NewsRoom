from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from framework.shared.result import ErrorDetail
from framework.shared.time import format_datetime
from framework.tool.governance.redaction import contains_redacted_value, redact_sensitive_values
from framework.tool.models.artifact_ref import ArtifactRef
from framework.tool.models.status import ToolStatus


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
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "output": redact_sensitive_values(self.output),
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
        }
