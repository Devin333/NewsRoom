from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from framework.events.envelope import EventEnvelope


@dataclass
class EventOrderingPolicy:
    next_sequence: int = 1

    def assign_sequence(self, envelope: EventEnvelope) -> EventEnvelope:
        if envelope.sequence is not None:
            return envelope
        assigned = envelope.with_sequence(self.next_sequence)
        self.next_sequence += 1
        return assigned

    def sort(self, events: Iterable[EventEnvelope]) -> list[EventEnvelope]:
        return sorted(
            events,
            key=lambda envelope: (
                envelope.sequence is None,
                envelope.sequence if envelope.sequence is not None else 0,
                envelope.event.created_at,
                envelope.event_id,
            ),
        )
