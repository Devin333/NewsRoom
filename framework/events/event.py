from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


class EventType(str, Enum):
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_FINISHED = "workflow_finished"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    TOOL_CALLED = "tool_called"
    AGENT_ITERATION = "agent_iteration"
    MEMORY_RECALLED = "memory_recalled"
    MEMORY_WRITTEN = "memory_written"
    WORKER_TASK_STARTED = "worker_task_started"
    WORKER_TASK_FINISHED = "worker_task_finished"


@dataclass(frozen=True)
class Event:
    event_type: str | EventType
    payload: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    run_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    component: str | None = None
    schema_version: str = "newsroom.event.v1"

    def __post_init__(self) -> None:
        event_type = self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type)
        if not event_type:
            raise ValueError("event_type is required")
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "payload": to_jsonable(self.payload),
            "source": self.source,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "component": self.component,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            source=data.get("source"),
            metadata=dict(data.get("metadata") or {}),
            created_at=parse_datetime(data.get("created_at")) or datetime.now(UTC),
            run_id=data.get("run_id"),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            workflow_id=data.get("workflow_id"),
            step_id=data.get("step_id"),
            component=data.get("component"),
            schema_version=str(data.get("schema_version") or "newsroom.event.v1"),
        )
