from __future__ import annotations

from collections.abc import Iterable

from framework.events.envelope import EventEnvelope
from framework.events.errors import EventReplayError
from framework.events.subscriber import EventSubscriber


class EventReplay:
    def replay(self, events: Iterable[EventEnvelope], subscriber: EventSubscriber) -> None:
        try:
            seen: dict[str, dict[str, object]] = {}
            for event in events:
                serialized = event.to_dict()
                previous = seen.get(event.event_id)
                if previous is not None:
                    if previous != serialized:
                        raise EventReplayError(
                            f"conflicting duplicate event during compatibility replay: {event.event_id}"
                        )
                    continue
                seen[event.event_id] = serialized
                subscriber.handle(event)
        except Exception as exc:
            raise EventReplayError("event replay failed") from exc
