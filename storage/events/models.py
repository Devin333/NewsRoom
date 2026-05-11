from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


_VALID_SEVERITIES = {"debug", "info", "warning", "error", "critical"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=_utc_now)
    workflow_id: str | None = None
    step_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    tool_call_id: str | None = None
    request_id: str | None = None
    severity: str = "info"
    trace_id: str | None = None
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "tool_call_id": self.tool_call_id,
            "request_id": self.request_id,
            "payload": _json_safe(self.payload),
            "severity": self.severity,
            "trace_id": self.trace_id,
            "redacted": self.redacted,
            "metadata": _json_safe(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EventRecord:
        timestamp = payload.get("timestamp", payload.get("occurred_at"))
        if timestamp is None:
            raise KeyError("timestamp")
        return cls(
            event_id=str(payload["event_id"]),
            run_id=str(payload["run_id"]),
            event_type=str(payload["event_type"]),
            timestamp=_parse_datetime(str(timestamp)),
            workflow_id=_optional_str(payload.get("workflow_id")),
            step_id=_optional_str(payload.get("step_id")),
            task_id=_optional_str(payload.get("task_id")),
            agent_id=_optional_str(payload.get("agent_id")),
            tool_call_id=_optional_str(payload.get("tool_call_id")),
            request_id=_optional_str(payload.get("request_id")),
            payload=dict(payload.get("payload") or {}),
            severity=str(payload.get("severity") or "info"),
            trace_id=_optional_str(payload.get("trace_id")),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
