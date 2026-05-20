from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared.time import utc_now
from framework.events.trace import TraceContext, trace_fields


@dataclass(frozen=True)
class MemoryTraceEvent:
    event_type: str
    memory_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    trace_context: TraceContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "memory_id": self.memory_id,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            **trace_fields(self.trace_context),
        }


class MemoryTraceRecorder:
    def __init__(self) -> None:
        self._events: list[MemoryTraceEvent] = []

    def record(self, event: MemoryTraceEvent) -> None:
        self._events.append(event)

    def list_events(self) -> list[MemoryTraceEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
