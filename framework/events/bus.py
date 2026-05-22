from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.events.envelope import EventEnvelope
from framework.events.errors import EventSubscriberError
from framework.events.event import Event
from framework.events.recorder import EventRecord
from framework.events.subscriber import EventSubscriber


@dataclass
class _Subscription:
    subscriber_id: str
    subscriber: Any
    legacy_callable: bool = False


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subscribers: list[_Subscription] = []
        self._published: list[EventEnvelope] = []

    def publish(self, event: Event | EventEnvelope | EventRecord) -> EventEnvelope:
        envelope = _to_envelope(event)
        self._published.append(envelope)
        for subscription in list(self._subscribers):
            try:
                if subscription.legacy_callable:
                    subscription.subscriber(event if isinstance(event, EventRecord) else envelope)
                else:
                    subscription.subscriber.handle(envelope)
            except Exception as exc:
                raise EventSubscriberError(
                    f"event subscriber failed: {subscription.subscriber_id}"
                ) from exc
        return envelope

    def subscribe(self, subscriber: EventSubscriber | Any) -> None:
        if hasattr(subscriber, "handle") and hasattr(subscriber, "subscriber_id"):
            self._subscribers.append(
                _Subscription(str(subscriber.subscriber_id), subscriber, legacy_callable=False)
            )
            return
        if callable(subscriber):
            subscriber_id = getattr(subscriber, "__name__", None) or f"subscriber_{id(subscriber)}"
            self._subscribers.append(
                _Subscription(str(subscriber_id), subscriber, legacy_callable=True)
            )
            return
        raise TypeError("event subscriber must be callable or implement EventSubscriber")

    def unsubscribe(self, subscriber_id: str) -> None:
        self._subscribers = [
            subscription
            for subscription in self._subscribers
            if subscription.subscriber_id != subscriber_id
        ]

    def list_subscribers(self) -> list[Any]:
        return [subscription.subscriber for subscription in self._subscribers]

    def published_events(self) -> list[EventEnvelope]:
        return list(self._published)

    def clear(self) -> None:
        self._published.clear()


EventBus = InMemoryEventBus


def _to_envelope(event: Event | EventEnvelope | EventRecord) -> EventEnvelope:
    if isinstance(event, EventEnvelope):
        return event
    if isinstance(event, EventRecord):
        return event.to_envelope()
    if isinstance(event, Event):
        return EventEnvelope(event=event)
    return EventEnvelope(event=Event.from_dict(dict(event)))
