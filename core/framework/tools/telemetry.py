from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.framework.tools.models import ToolCall, ToolObservation, ToolResult, ToolStatus
from core.framework.tools.redaction import redact_sensitive_values


@dataclass(frozen=True)
class ToolEvent:
    event_type: str
    tool_name: str
    tool_call_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "payload": redact_sensitive_values(self.payload),
        }


@dataclass
class ToolMetrics:
    total_calls: int = 0
    succeeded_calls: int = 0
    failed_calls: int = 0
    blocked_calls: int = 0
    approval_required_calls: int = 0
    timeout_calls: int = 0
    total_elapsed_ms: float = 0.0
    total_output_bytes: int = 0
    spilled_result_count: int = 0
    calls_by_tool: dict[str, int] = field(default_factory=dict)
    failures_by_error_type: dict[str, int] = field(default_factory=dict)

    def record(self, observation: ToolObservation) -> None:
        self.total_calls += 1
        self.calls_by_tool[observation.call.tool_name] = (
            self.calls_by_tool.get(observation.call.tool_name, 0) + 1
        )
        self.total_elapsed_ms += observation.elapsed_ms
        if observation.result.output_bytes:
            self.total_output_bytes += observation.result.output_bytes
        if observation.result.artifact_refs:
            self.spilled_result_count += 1

        if observation.status == ToolStatus.SUCCEEDED:
            self.succeeded_calls += 1
        elif observation.status == ToolStatus.FAILED:
            self.failed_calls += 1
            self._record_error_type(observation.result.error_type)
        elif observation.status == ToolStatus.BLOCKED:
            self.blocked_calls += 1
            self._record_error_type(observation.result.error_type)
        elif observation.status == ToolStatus.APPROVAL_REQUIRED:
            self.approval_required_calls += 1
        elif observation.status == ToolStatus.TIMEOUT:
            self.timeout_calls += 1
            self._record_error_type(observation.result.error_type)

    def snapshot(self) -> ToolMetrics:
        return ToolMetrics(
            total_calls=self.total_calls,
            succeeded_calls=self.succeeded_calls,
            failed_calls=self.failed_calls,
            blocked_calls=self.blocked_calls,
            approval_required_calls=self.approval_required_calls,
            timeout_calls=self.timeout_calls,
            total_elapsed_ms=self.total_elapsed_ms,
            total_output_bytes=self.total_output_bytes,
            spilled_result_count=self.spilled_result_count,
            calls_by_tool=dict(self.calls_by_tool),
            failures_by_error_type=dict(self.failures_by_error_type),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "succeeded_calls": self.succeeded_calls,
            "failed_calls": self.failed_calls,
            "blocked_calls": self.blocked_calls,
            "approval_required_calls": self.approval_required_calls,
            "timeout_calls": self.timeout_calls,
            "total_elapsed_ms": self.total_elapsed_ms,
            "total_output_bytes": self.total_output_bytes,
            "spilled_result_count": self.spilled_result_count,
            "calls_by_tool": dict(self.calls_by_tool),
            "failures_by_error_type": dict(self.failures_by_error_type),
        }

    def _record_error_type(self, error_type: str | None) -> None:
        if not error_type:
            return
        self.failures_by_error_type[error_type] = (
            self.failures_by_error_type.get(error_type, 0) + 1
        )


@dataclass(frozen=True)
class ToolExecutionRecord:
    tool_call: ToolCall
    tool_result: ToolResult
    validation_passed: bool
    guardrails_passed: bool
    approval_required: bool
    approval_id: str | None
    started_at: datetime
    finished_at: datetime
    events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call": self.tool_call.to_dict(),
            "tool_result": self.tool_result.to_dict(),
            "validation_passed": self.validation_passed,
            "guardrails_passed": self.guardrails_passed,
            "approval_required": self.approval_required,
            "approval_id": self.approval_id,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": self.finished_at.isoformat().replace("+00:00", "Z"),
            "events": list(self.events),
        }
