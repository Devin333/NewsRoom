from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.framework.serialization import to_json_safe


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "occurred_at": to_json_safe(self.occurred_at),
            "payload": to_json_safe(self.payload),
        }


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Any] = []

    def subscribe(self, subscriber: Any) -> None:
        if not callable(subscriber):
            raise TypeError("event subscriber must be callable")
        self._subscribers.append(subscriber)

    def publish(self, event: EventRecord) -> None:
        for subscriber in list(self._subscribers):
            subscriber(event)


class EventRecorder:
    def __init__(self, run_id: str, event_bus: EventBus | None = None) -> None:
        self.run_id = run_id
        self._event_bus = event_bus
        self._events: list[EventRecord] = []

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> EventRecord:
        event = EventRecord(run_id=self.run_id, event_type=event_type, payload=payload or {})
        self._events.append(event)
        if self._event_bus is not None:
            self._event_bus.publish(event)
        return event

    def list_events(self) -> list[EventRecord]:
        return list(self._events)

    def write_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return target
