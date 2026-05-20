from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from framework.shared.ids import generate_id
from framework.events.event import Event


@dataclass(frozen=True)
class EventEnvelope:
    event: Event
    event_id: str = field(default_factory=lambda: generate_id("evt"))
    correlation_id: str | None = None
    causation_id: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not isinstance(self.event, Event):
            object.__setattr__(self, "event", Event.from_dict(dict(self.event)))

    def with_sequence(self, sequence: int) -> "EventEnvelope":
        return replace(self, sequence=int(sequence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event": self.event.to_dict(),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "sequence": self.sequence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        return cls(
            event_id=str(data["event_id"]),
            event=Event.from_dict(dict(data["event"])),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            sequence=data.get("sequence"),
        )
