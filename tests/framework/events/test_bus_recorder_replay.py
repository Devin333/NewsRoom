from __future__ import annotations

from collections.abc import Callable

import pytest

from framework.events import (
    Event,
    EventEnvelope,
    EventOrderingPolicy,
    InMemoryEventBus,
    InMemoryEventRecorder,
)


class _CallbackSubscriber:
    def __init__(
        self,
        callback: Callable[[EventEnvelope], None],
        *,
        subscriber_id: str,
    ) -> None:
        self.callback = callback
        self.subscriber_id = subscriber_id

    def handle(self, envelope: EventEnvelope) -> None:
        self.callback(envelope)


def test_event_bus_publishes_one_envelope_type_for_supported_inputs() -> None:
    bus = InMemoryEventBus()
    received: list[EventEnvelope] = []
    bus.subscribe(_CallbackSubscriber(received.append, subscriber_id="recorder"))

    envelope = bus.publish(Event("tool_called", {"tool": "search"}))

    assert envelope.event.event_type == "tool_called"
    assert received == [envelope]

    same = bus.publish(envelope)
    assert same is envelope
    with pytest.raises(TypeError, match="Event or EventEnvelope"):
        bus.publish({"event_type": "workflow_started"})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="implement EventSubscriber"):
        bus.subscribe(received.append)  # type: ignore[arg-type]


def test_in_memory_bus_recorder_and_ordering_are_explicit_test_adapters() -> None:
    bus = InMemoryEventBus()
    recorder = InMemoryEventRecorder()
    bus.subscribe(_CallbackSubscriber(recorder.record, subscriber_id="recorder"))

    first = bus.publish(Event("memory_recalled", {"count": 2}, source="memory"))
    second = bus.publish(Event("memory_written", {"count": 1}, source="memory"))
    ordering = EventOrderingPolicy()
    ordered = [ordering.assign_sequence(first), ordering.assign_sequence(second)]

    assert [event.event.event_type for event in recorder.list_events()] == [
        "memory_recalled",
        "memory_written",
    ]
    assert [event.sequence for event in ordering.sort(reversed(ordered))] == [1, 2]
