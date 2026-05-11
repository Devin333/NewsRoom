from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


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
            "occurred_at": _json_safe(self.occurred_at),
            "payload": _json_safe(self.payload),
        }


class EventRecorder:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._events: list[EventRecord] = []

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> EventRecord:
        event = EventRecord(run_id=self.run_id, event_type=event_type, payload=payload or {})
        self._events.append(event)
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
