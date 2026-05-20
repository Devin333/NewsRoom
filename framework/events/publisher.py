from __future__ import annotations

from typing import Any

from framework.events.bus import EventBus
from framework.events.envelope import EventEnvelope
from framework.events.event import Event


class EventPublisher:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        return self.bus.publish(
            Event(
                event_type=event_type,
                payload=payload or {},
                source=source,
                metadata=metadata or {},
            )
        )
