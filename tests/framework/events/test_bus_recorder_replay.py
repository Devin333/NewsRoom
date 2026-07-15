from __future__ import annotations

from framework.events import (
    Event,
    EventBus,
    EventOrderingPolicy,
    EventPublisher,
    EventRecord,
    EventRecorder,
    EventReplay,
    FunctionEventSubscriber,
    InMemoryEventRecorder,
)


def test_event_bus_publishes_one_envelope_type_for_legacy_inputs() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(received.append)

    envelope = bus.publish(Event("tool_called", {"tool": "search"}))

    assert envelope.event.event_type == "tool_called"
    assert received == [envelope]

    legacy_events = []
    legacy_bus = EventBus()
    legacy_bus.subscribe(legacy_events.append)
    record = EventRecord(run_id="run-1", event_type="workflow_started")
    legacy_bus.publish(record)

    assert len(legacy_events) == 1
    assert legacy_events[0].event_id == record.event_id
    assert legacy_events[0].event.event_type == record.event_type


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


def test_legacy_event_recorder_emit_write_and_list(tmp_path) -> None:
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    recorder = EventRecorder("run-1", event_bus=bus)

    emitted = recorder.emit("step_finished", {"step_id": "draft"})
    target = recorder.write_jsonl(tmp_path / "events.jsonl")

    assert recorder.list_events() == [emitted]
    assert events == [emitted]
    assert "step_finished" in target.read_text(encoding="utf-8")
