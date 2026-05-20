from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared.time import ensure_utc
from framework.events.envelope import EventEnvelope


@dataclass(frozen=True)
class EventFilter:
    event_types: list[str] = field(default_factory=list)
    source: str | None = None
    correlation_id: str | None = None
    time_window: Any | None = None

    def matches(self, envelope: EventEnvelope) -> bool:
        if self.event_types and envelope.event.event_type not in set(self.event_types):
            return False
        if self.source is not None and envelope.event.source != self.source:
            return False
        if self.correlation_id is not None and envelope.correlation_id != self.correlation_id:
            return False
        if self.time_window is not None and not _time_window_contains(
            self.time_window,
            envelope.event.created_at,
        ):
            return False
        return True


def _time_window_contains(time_window: Any, moment: datetime) -> bool:
    contains = getattr(time_window, "contains", None)
    if callable(contains):
        return bool(contains(moment))
    start = getattr(time_window, "start", None) or getattr(time_window, "start_at", None)
    end = getattr(time_window, "end", None) or getattr(time_window, "end_at", None)
    actual = ensure_utc(moment)
    if start is not None and actual < ensure_utc(start):
        return False
    if end is not None and actual > ensure_utc(end):
        return False
    return True
