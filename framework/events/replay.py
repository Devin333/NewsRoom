from __future__ import annotations

from collections.abc import Iterable

from framework.events.bus import EventBus
from framework.events.envelope import EventEnvelope
from framework.events.errors import EventReplayError
from framework.events.subscriber import EventSubscriber


class EventReplay:
    def replay(self, events: Iterable[EventEnvelope], subscriber: EventSubscriber) -> None:
        try:
            for event in events:
                subscriber.handle(event)
        except Exception as exc:
            raise EventReplayError("event replay failed") from exc

    def replay_to_bus(self, events: Iterable[EventEnvelope], bus: EventBus) -> None:
        try:
            for event in events:
                bus.publish(event)
        except Exception as exc:
            raise EventReplayError("event replay to bus failed") from exc
