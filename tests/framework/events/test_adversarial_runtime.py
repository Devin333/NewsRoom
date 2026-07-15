from __future__ import annotations

import pytest

from framework.events import (
    Event,
    EventBus,
    EventEnvelope,
    EventQuarantineError,
    EventReplay,
    EventRuntimeError,
    EventSubscriberError,
    FunctionEventSubscriber,
    TraceContext,
    TraceEvent,
    default_event_schema_catalog,
)


def test_event_copies_nested_input_before_accepting_snapshot() -> None:
    source_payload = {
        "nested": {
            "items": [
                {"value": "accepted"},
            ]
        }
    }
    event = Event("workflow_started", payload=source_payload)
    accepted_payload = event.to_dict()["payload"]

    source_payload["nested"]["items"][0]["value"] = "caller-mutated"
    source_payload["nested"]["items"].append({"value": "caller-added"})

    assert event.to_dict()["payload"] == accepted_payload


def test_event_returned_payload_view_cannot_mutate_accepted_snapshot() -> None:
    event = Event(
        "workflow_started",
        payload={"nested": {"items": [{"value": "accepted"}]}},
    )
    accepted_payload = event.to_dict()["payload"]
    returned_view = event.payload

    try:
        returned_view["nested"]["items"][0]["value"] = "view-mutated"
    except (AttributeError, TypeError):
        pass
    try:
        returned_view["added_after_creation"] = True
    except (AttributeError, TypeError):
        pass

    assert event.to_dict()["payload"] == accepted_payload


@pytest.mark.parametrize("mutable_leaf", [bytearray(b"secret"), object()])
def test_legacy_event_rejects_unsupported_mutable_leaf(mutable_leaf: object) -> None:
    with pytest.raises((EventRuntimeError, TypeError, ValueError)):
        Event("workflow_started", payload={"unsupported": mutable_leaf})


@pytest.mark.parametrize(
    ("field", "event_value", "envelope_value"),
    [
        ("run_id", "run-event", "run-envelope"),
        ("trace_id", "trace-event", "trace-envelope"),
    ],
)
def test_event_envelope_rejects_conflicting_context(
    field: str,
    event_value: str,
    envelope_value: str,
) -> None:
    event = Event("step_started", **{field: event_value})

    with pytest.raises((EventRuntimeError, ValueError)):
        EventEnvelope(
            event=event,
            event_id=f"evt-conflicting-{field}",
            **{field: envelope_value},
        )


def test_event_envelope_accepts_equal_legacy_duplicate_context() -> None:
    envelope = EventEnvelope(
        event=Event(
            "step_started",
            run_id="run-equal",
            trace_id="trace-equal",
        ),
        event_id="evt-equal-context",
        run_id="run-equal",
        trace_id="trace-equal",
    )

    restored = EventEnvelope.from_dict(envelope.to_dict())

    assert (restored.run_id, restored.trace_id) == ("run-equal", "trace-equal")


class _SubscriberFailure(RuntimeError):
    pass


def test_subscriber_failure_does_not_block_later_subscriber_and_keeps_cause() -> None:
    bus = EventBus()
    calls: list[str] = []
    cause = _SubscriberFailure("second subscriber failed")

    def first(envelope: EventEnvelope) -> None:
        calls.append("first")

    def second(envelope: EventEnvelope) -> None:
        calls.append("second")
        raise cause

    def third(envelope: EventEnvelope) -> None:
        calls.append("third")

    bus.subscribe(first)
    bus.subscribe(second)
    bus.subscribe(third)

    with pytest.raises(EventSubscriberError) as caught:
        bus.publish(Event("workflow_started"))

    assert (calls, caught.value.__cause__) == (["first", "second", "third"], cause)


def test_compatibility_replay_deduplicates_event_id_before_effect() -> None:
    envelope = EventEnvelope(
        event=Event("step_finished", run_id="run-replay"),
        event_id="evt-replayed-once",
        run_id="run-replay",
    )
    duplicate_identity = EventEnvelope.from_dict(envelope.to_dict())
    applied_event_ids: list[str] = []

    EventReplay().replay(
        [envelope, duplicate_identity],
        FunctionEventSubscriber(
            lambda item: applied_event_ids.append(item.event_id),
            subscriber_id="compatibility-effect",
        ),
    )

    assert applied_event_ids == ["evt-replayed-once"]


@pytest.mark.parametrize(
    "time_fields",
    [{}, {"created_at": ""}],
    ids=["missing", "blank"],
)
def test_event_history_without_occurrence_time_fails_closed(
    time_fields: dict[str, str],
) -> None:
    payload = {
        "schema_version": "newsroom.event.v1",
        "event_type": "workflow_started",
        "payload": {},
        **time_fields,
    }

    with pytest.raises((KeyError, ValueError)):
        Event.from_dict(payload)


@pytest.mark.parametrize(
    "time_fields",
    [{}, {"occurred_at": ""}],
    ids=["missing", "blank"],
)
def test_framework_event_record_history_without_occurrence_time_is_quarantined(
    time_fields: dict[str, str],
) -> None:
    with pytest.raises(EventQuarantineError, match="missing_occurred_at"):
        default_event_schema_catalog().resolve_historical(
            "workflow_started",
            "newsroom.workflow-event/v1",
            {"workflow_version": "1", "profile": "default"},
            occurred_at=time_fields.get("occurred_at"),
            envelope_schema="newsroom.event_record.v1",
        )


@pytest.mark.parametrize(
    "time_fields",
    [{}, {"timestamp": ""}],
    ids=["missing", "blank"],
)
def test_trace_event_history_without_occurrence_time_fails_closed(
    time_fields: dict[str, str],
) -> None:
    payload = {
        "schema_version": "newsroom.trace_event.v1",
        "event_id": "trace-event-missing-time",
        "event_type": "step_started",
        "context": TraceContext.root(run_id="run-trace-missing-time").to_dict(),
        "component": "workflow",
        "operation": "step",
        "status": "started",
        **time_fields,
    }

    with pytest.raises((KeyError, ValueError)):
        TraceEvent.from_dict(payload)
