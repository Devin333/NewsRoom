from __future__ import annotations

from typing import Protocol

from framework.events.envelope import EventEnvelope
from framework.events.filters import EventFilter


class EventRecorderProtocol(Protocol):
    def record(self, envelope: EventEnvelope) -> None: ...

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]: ...


class InMemoryEventRecorder:
    """Explicit test adapter; production workflow events use the durable runtime."""

    def __init__(self, envelopes: list[EventEnvelope] | None = None) -> None:
        self._events = list(envelopes or [])

    def record(self, envelope: EventEnvelope) -> None:
        self._events.append(envelope)

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]:
        events = list(self._events)
        if filters is not None:
            return [event for event in events if filters.matches(event)]
        return events

    def clear(self) -> None:
        self._events.clear()
