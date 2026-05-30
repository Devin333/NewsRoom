from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from uuid import uuid4

from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc, parse_datetime


_VALID_SEVERITIES = {"debug", "info", "warning", "error", "critical"}


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
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
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))

    @property
    def occurred_at(self) -> datetime:
        return self.timestamp

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
            "payload": to_jsonable(self.payload),
            "severity": self.severity,
            "trace_id": self.trace_id,
            "redacted": self.redacted,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventRecord":
        timestamp = payload.get("timestamp", payload.get("occurred_at"))
        if timestamp is None:
            raise KeyError("timestamp")
        return cls(
            event_id=str(payload["event_id"]),
            run_id=str(payload["run_id"]),
            event_type=str(payload["event_type"]),
            timestamp=parse_datetime(timestamp) or datetime.now(UTC),
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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
