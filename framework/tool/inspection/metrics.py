from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from uuid import uuid4

from framework.tool.governance.redaction import redact_sensitive_values
from framework.events.trace import TraceContext, trace_fields
from framework.tool.models.call import ToolCall
from framework.tool.models.observation import ToolObservation
from framework.tool.models.result import ToolResult
from framework.tool.models.status import ToolStatus


@dataclass(frozen=True)
class ToolEvent:
    event_type: str
    tool_name: str
    tool_call_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    run_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None

    @classmethod
    def from_trace(
        cls,
        *,
        event_type: str,
        tool_name: str,
        tool_call_id: str,
        payload: dict[str, Any] | None = None,
        trace_context: TraceContext | None = None,
    ) -> "ToolEvent":
        context = (
            trace_context.child(
                span_id=f"tool:{tool_call_id}",
                tool_call_id=tool_call_id,
            )
            if trace_context is not None
            else None
        )
        fields = trace_fields(context)
        return cls(
            event_type=event_type,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            payload=dict(payload or {}),
            trace_id=fields.get("trace_id"),
            span_id=fields.get("span_id"),
            parent_span_id=fields.get("parent_span_id"),
            run_id=fields.get("run_id"),
            workflow_id=fields.get("workflow_id"),
            step_id=fields.get("step_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "payload": redact_sensitive_values(self.payload),
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
        }


@dataclass
class ToolMetrics:
    total_calls: int = 0
    succeeded_calls: int = 0
    failed_calls: int = 0
    blocked_calls: int = 0
    approval_required_calls: int = 0
    timeout_calls: int = 0
    denied_calls: int = 0
    skipped_calls: int = 0
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
        elif observation.status == ToolStatus.DENIED:
            self.denied_calls += 1
            self._record_error_type(observation.result.error_type)
        elif observation.status == ToolStatus.SKIPPED:
            self.skipped_calls += 1
        elif observation.status == ToolStatus.APPROVAL_REQUIRED:
            self.approval_required_calls += 1
        elif observation.status == ToolStatus.TIMEOUT:
            self.timeout_calls += 1
            self._record_error_type(observation.result.error_type)

    def snapshot(self) -> "ToolMetrics":
        return ToolMetrics(
            total_calls=self.total_calls,
            succeeded_calls=self.succeeded_calls,
            failed_calls=self.failed_calls,
            blocked_calls=self.blocked_calls,
            approval_required_calls=self.approval_required_calls,
            timeout_calls=self.timeout_calls,
            denied_calls=self.denied_calls,
            skipped_calls=self.skipped_calls,
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
            "denied_calls": self.denied_calls,
            "skipped_calls": self.skipped_calls,
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


class ToolMetricsCollector:
    def __init__(self) -> None:
        self.metrics = ToolMetrics()

    def record(self, result: ToolResult | ToolObservation) -> None:
        if isinstance(result, ToolObservation):
            self.metrics.record(result)
            return
        call = ToolCall(tool_name=result.tool_name or "unknown", call_id=result.call_id or "")
        self.metrics.record(ToolObservation(call=call, result=result))

    def snapshot(self) -> ToolMetrics:
        return self.metrics.snapshot()


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
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    gate_result: dict[str, Any] | None = None
    policy_trace: dict[str, Any] | None = None
    error_envelope: dict[str, Any] | None = None
    retry_count: int = 0
    timeout: bool = False

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
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "gate_result": dict(self.gate_result) if self.gate_result is not None else None,
            "policy_trace": (
                dict(self.policy_trace) if self.policy_trace is not None else None
            ),
            "error_envelope": (
                dict(self.error_envelope) if self.error_envelope is not None else None
            ),
            "retry_count": self.retry_count,
            "timeout": self.timeout,
        }
