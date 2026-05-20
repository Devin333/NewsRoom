from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


TRACE_EVENT_SCHEMA_VERSION = "newsroom.trace_event.v1"

_SENSITIVE_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class TraceContext:
    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    agent_id: str | None = None
    tool_call_id: str | None = None
    memory_operation_id: str | None = None
    artifact_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.trace_id:
            raise ValueError("trace_id is required")
        if not self.span_id:
            raise ValueError("span_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def root(
        cls,
        *,
        run_id: str,
        workflow_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "TraceContext":
        return cls(
            run_id=run_id,
            trace_id=trace_id or uuid4().hex,
            span_id=span_id or f"workflow:{run_id}",
            workflow_id=workflow_id,
            metadata=dict(metadata or {}),
        )

    def child(
        self,
        *,
        span_id: str | None = None,
        step_id: str | None = None,
        agent_id: str | None = None,
        tool_call_id: str | None = None,
        memory_operation_id: str | None = None,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "TraceContext":
        return TraceContext(
            run_id=self.run_id,
            trace_id=self.trace_id,
            span_id=span_id or uuid4().hex,
            parent_span_id=self.span_id,
            workflow_id=self.workflow_id,
            step_id=step_id if step_id is not None else self.step_id,
            agent_id=agent_id if agent_id is not None else self.agent_id,
            tool_call_id=tool_call_id if tool_call_id is not None else self.tool_call_id,
            memory_operation_id=(
                memory_operation_id
                if memory_operation_id is not None
                else self.memory_operation_id
            ),
            artifact_id=artifact_id if artifact_id is not None else self.artifact_id,
            metadata={**self.metadata, **dict(metadata or {})},
        )

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        metadata = dict(self.metadata)
        if redact:
            metadata = redact_trace_payload(metadata)
        return {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "agent_id": self.agent_id,
            "tool_call_id": self.tool_call_id,
            "memory_operation_id": self.memory_operation_id,
            "artifact_id": self.artifact_id,
            "metadata": to_jsonable(metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceContext":
        return cls(
            run_id=str(payload["run_id"]),
            trace_id=str(payload["trace_id"]),
            span_id=str(payload["span_id"]),
            parent_span_id=_optional_str(payload.get("parent_span_id")),
            workflow_id=_optional_str(payload.get("workflow_id")),
            step_id=_optional_str(payload.get("step_id")),
            agent_id=_optional_str(payload.get("agent_id")),
            tool_call_id=_optional_str(payload.get("tool_call_id")),
            memory_operation_id=_optional_str(payload.get("memory_operation_id")),
            artifact_id=_optional_str(payload.get("artifact_id")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class TraceEvent:
    event_type: str
    context: TraceContext
    component: str
    operation: str
    status: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    schema_version: str = TRACE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event_type is required")
        if not self.component:
            raise ValueError("component is required")
        if not self.operation:
            raise ValueError("operation is required")
        if not self.status:
            raise ValueError("status is required")
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "payload", dict(self.payload or {}))
        if self.error is not None:
            object.__setattr__(self, "error", dict(self.error))

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = dict(self.payload)
        error = dict(self.error) if self.error is not None else None
        if redact:
            payload = redact_trace_payload(payload)
            error = redact_trace_payload(error) if isinstance(error, dict) else error
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": format_datetime(self.timestamp),
            "context": self.context.to_dict(redact=redact),
            "component": self.component,
            "operation": self.operation,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "payload": to_jsonable(payload),
            "error": to_jsonable(error),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceEvent":
        return cls(
            schema_version=str(payload.get("schema_version") or TRACE_EVENT_SCHEMA_VERSION),
            event_id=str(payload.get("event_id") or uuid4().hex),
            event_type=str(payload["event_type"]),
            timestamp=parse_datetime(payload.get("timestamp")) or datetime.now(UTC),
            context=TraceContext.from_dict(dict(payload["context"])),
            component=str(payload["component"]),
            operation=str(payload["operation"]),
            status=str(payload["status"]),
            duration_ms=(
                float(payload["duration_ms"])
                if payload.get("duration_ms") is not None
                else None
            ),
            payload=dict(payload.get("payload") or {}),
            error=dict(payload["error"]) if isinstance(payload.get("error"), dict) else None,
        )


def trace_fields(context: TraceContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        "run_id": context.run_id,
        "trace_id": context.trace_id,
        "span_id": context.span_id,
        "parent_span_id": context.parent_span_id,
        "workflow_id": context.workflow_id,
        "step_id": context.step_id,
    }


def redact_trace_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = redact_trace_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_trace_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_trace_payload(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    key_lower = key.casefold()
    return any(token in key_lower for token in _SENSITIVE_TOKENS)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
