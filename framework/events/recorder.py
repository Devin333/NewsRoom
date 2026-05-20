from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime
from framework.events.envelope import EventEnvelope
from framework.events.event import Event
from framework.events.filters import EventFilter


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.event_type:
            raise ValueError("event_type is required")
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))

    def to_event(self) -> Event:
        return Event(
            event_type=self.event_type,
            payload=self.payload,
            source="workflow",
            metadata={"run_id": self.run_id},
            created_at=self.occurred_at,
        )

    def to_envelope(self) -> EventEnvelope:
        return EventEnvelope(
            event_id=self.event_id,
            event=self.to_event(),
            correlation_id=self.run_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "occurred_at": format_datetime(self.occurred_at),
            "payload": to_jsonable(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventRecord":
        return cls(
            run_id=str(data["run_id"]),
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            event_id=str(data.get("event_id") or uuid4().hex),
            occurred_at=parse_datetime(data.get("occurred_at") or data.get("timestamp")) or datetime.now(UTC),
        )


class EventRecorderProtocol(Protocol):
    def record(self, envelope: EventEnvelope) -> None: ...

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]: ...


class InMemoryEventRecorder:
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


class EventRecorder:
    """Legacy workflow recorder with PRD record/list support."""

    def __init__(self, run_id: str | None = None, event_bus: Any | None = None) -> None:
        self.run_id = run_id
        self._event_bus = event_bus
        self._records: list[EventRecord] = []
        self._envelopes: list[EventEnvelope] = []

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> EventRecord:
        if not self.run_id:
            raise ValueError("run_id is required for emit()")
        event = EventRecord(run_id=self.run_id, event_type=event_type, payload=payload or {})
        self._records.append(event)
        self._envelopes.append(event.to_envelope())
        if self._event_bus is not None:
            self._event_bus.publish(event)
        return event

    def record(self, envelope: EventEnvelope) -> None:
        self._envelopes.append(envelope)

    def list_events(self, filters: EventFilter | None = None) -> list[Any]:
        if filters is None and self._records:
            return list(self._records)
        events = list(self._envelopes)
        if filters is not None:
            return [event for event in events if filters.matches(event)]
        return events

    def write_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self._records:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return target
