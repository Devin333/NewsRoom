from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared.time import utc_now


@dataclass(frozen=True)
class MemoryTraceEvent:
    event_type: str
    memory_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


class MemoryTraceRecorder:
    def __init__(self) -> None:
        self._events: list[MemoryTraceEvent] = []

    def record(self, event: MemoryTraceEvent) -> None:
        self._events.append(event)

    def list_events(self) -> list[MemoryTraceEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
