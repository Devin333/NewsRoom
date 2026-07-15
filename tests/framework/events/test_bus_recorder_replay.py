from __future__ import annotations

import pytest

from framework.events import (
    Event,
    EventBus,
    EventOrderingPolicy,
    EventPublisher,
    EventReplay,
    FunctionEventSubscriber,
    InMemoryEventRecorder,
)


def test_event_bus_publishes_one_envelope_type_for_supported_inputs() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(received.append)

    envelope = bus.publish(Event("tool_called", {"tool": "search"}))

    assert envelope.event.event_type == "tool_called"
    assert received == [envelope]

    same = bus.publish(envelope)
    assert same is envelope
    with pytest.raises(TypeError, match="Event or EventEnvelope"):
        bus.publish({"event_type": "workflow_started"})  # type: ignore[arg-type]


def test_publisher_recorder_ordering_and_replay() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus)
    recorder = InMemoryEventRecorder()
    bus.subscribe(FunctionEventSubscriber(recorder.record, subscriber_id="recorder"))

    first = publisher.publish("memory_recalled", {"count": 2}, source="memory")
    second = publisher.publish("memory_written", {"count": 1}, source="memory")
    ordering = EventOrderingPolicy()
    ordered = [ordering.assign_sequence(first), ordering.assign_sequence(second)]

    replayed = []
    EventReplay().replay(ordered, FunctionEventSubscriber(replayed.append))

    assert [event.event.event_type for event in recorder.list_events()] == [
        "memory_recalled",
        "memory_written",
    ]
    assert [event.sequence for event in ordering.sort(reversed(ordered))] == [1, 2]
    assert replayed == ordered
