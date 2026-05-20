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
            "event_type": self.event_type,
            "payload": to_jsonable(self.payload),
            "source": self.source,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            source=data.get("source"),
            metadata=dict(data.get("metadata") or {}),
            created_at=parse_datetime(data.get("created_at")) or datetime.now(UTC),
        )
