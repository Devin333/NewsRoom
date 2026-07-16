from __future__ import annotations

from dataclasses import dataclass

from framework.events.envelope import EventEnvelope
from framework.events.errors import EventSubscriberError
from framework.events.event import Event
from framework.events.subscriber import EventSubscriber


@dataclass
class _Subscription:
    subscriber_id: str
    subscriber: EventSubscriber


class InMemoryEventBus:
    """Process-local event adapter for tests; it is not a durable publisher."""

    def __init__(self) -> None:
        self._subscribers: list[_Subscription] = []
        self._published: list[EventEnvelope] = []

    def publish(self, event: Event | EventEnvelope) -> EventEnvelope:
        envelope = _to_envelope(event)
        self._published.append(envelope)
        first_failure: tuple[str, Exception] | None = None
        for subscription in list(self._subscribers):
            try:
                subscription.subscriber.handle(envelope)
            except Exception as exc:
                if first_failure is None:
                    first_failure = (subscription.subscriber_id, exc)
        if first_failure is not None:
            subscriber_id, cause = first_failure
            raise EventSubscriberError(f"event subscriber failed: {subscriber_id}") from cause
        return envelope

    def subscribe(self, subscriber: EventSubscriber) -> None:
        if hasattr(subscriber, "handle") and hasattr(subscriber, "subscriber_id"):
            self._subscribers.append(
                _Subscription(str(subscriber.subscriber_id), subscriber)
            )
            return
        raise TypeError("event subscriber must implement EventSubscriber")

    def unsubscribe(self, subscriber_id: str) -> None:
        self._subscribers = [
            subscription
            for subscription in self._subscribers
            if subscription.subscriber_id != subscriber_id
        ]

    def list_subscribers(self) -> list[EventSubscriber]:
        return [subscription.subscriber for subscription in self._subscribers]

    def published_events(self) -> list[EventEnvelope]:
        return list(self._published)

    def clear(self) -> None:
        self._published.clear()


def _to_envelope(event: Event | EventEnvelope) -> EventEnvelope:
    if isinstance(event, EventEnvelope):
        return event
    if isinstance(event, Event):
        return EventEnvelope(event=event)
    raise TypeError("event bus accepts Event or EventEnvelope")
