from __future__ import annotations

import json

import pytest

from framework.events import (
    Event,
    EventBus,
    EventEnvelope,
    EventRecord as FrameworkEventRecord,
    EventRecorder,
    EventReplay,
    EventRuntimeError,
    EventSecurePayloadRequiredError,
    EventSubscriberError,
    FunctionEventSubscriber,
    TraceContext,
    TraceEvent,
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


def test_recorder_emit_and_record_share_one_identity_ledger(tmp_path) -> None:
    recorder = EventRecorder("run-recorder-ledger")
    emitted = recorder.emit(
        "step_started",
        {
            "step_id": "collect",
            "step_type": "source",
            "attempt": 1,
            "max_attempts": 1,
        },
    )
    recorded = EventEnvelope(
        event=Event(
            "step_finished",
            {"step_id": "collect"},
            run_id="run-recorder-ledger",
        ),
        event_id="evt-recorded-directly",
        run_id="run-recorder-ledger",
    )
    recorder.record(recorded)

    listed = recorder.list_events()
    target = recorder.write_jsonl(tmp_path / "events.jsonl")
    jsonl_rows = [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected_ids = [emitted.event_id, recorded.event_id]

    assert {
        "listed": [event.event_id for event in listed],
        "jsonl": [row["event_id"] for row in jsonl_rows],
    } == {
        "listed": expected_ids,
        "jsonl": expected_ids,
    }


def test_recorder_emit_and_list_have_one_envelope_type() -> None:
    recorder = EventRecorder("run-recorder-types")
    emitted = recorder.emit("step_started", {"step_id": "collect"})
    recorder.record(
        EventEnvelope(
            event=Event("step_finished", run_id="run-recorder-types"),
            event_id="evt-recorded-type",
            run_id="run-recorder-types",
        )
    )
    listed = recorder.list_events()

    assert type(emitted) is EventEnvelope
    assert listed
    assert {type(event) for event in listed} == {EventEnvelope}


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


def test_write_jsonl_never_persists_raw_secret_sentinel(tmp_path) -> None:
    raw_secret = "sk-DURABLEEVENTSENTINEL123456789"
    recorder = EventRecorder("run-secret-export")
    recorder.emit(
        "tool_called",
        {
            "credentials": {"api_key": raw_secret},
            "diagnostic": f"Bearer {raw_secret}",
        },
    )

    target = recorder.write_jsonl(tmp_path / "events.jsonl")

    assert raw_secret not in target.read_text(encoding="utf-8")


def test_write_jsonl_redacts_metadata_and_duplicate_diagnostics(tmp_path) -> None:
    raw_secret = "metadata-DURABLEEVENTSENTINEL123456789"
    recorder = EventRecorder("run-secret-metadata-export")
    recorder.record(
        EventEnvelope(
            event=Event(
                "tool_called",
                payload={"safe": True},
                metadata={
                    "authorization": f"Bearer {raw_secret}",
                    "diagnostic": f"request failed with {raw_secret}",
                },
                run_id="run-secret-metadata-export",
            ),
            event_id="evt-secret-metadata",
            run_id="run-secret-metadata-export",
        )
    )

    target = recorder.write_jsonl(tmp_path / "events.jsonl")
    content = target.read_text(encoding="utf-8")

    assert raw_secret not in content
    assert "[REDACTED]" in content


def test_write_jsonl_applies_schema_sensitive_policy_before_export(tmp_path) -> None:
    raw_secret = "schema-sensitive-export-sentinel"
    recorder = EventRecorder("run-schema-sensitive-export")
    recorder.record(
        EventEnvelope(
            event=Event(
                "workflow_resumed",
                payload={
                    "workflow_id": "workflow-1",
                    "workflow_version": "v1",
                    "profile": "default",
                    "checkpoint_id": "checkpoint-1",
                    "resume_metadata": {"credential": raw_secret},
                },
                metadata={
                    "diagnostic": f"resume failed for {raw_secret}",
                },
                run_id="run-schema-sensitive-export",
            ),
            event_id="evt-schema-sensitive-export",
            run_id="run-schema-sensitive-export",
        )
    )

    target = recorder.write_jsonl(tmp_path / "events.jsonl")
    content = target.read_text(encoding="utf-8")
    row = json.loads(content)

    assert raw_secret not in content
    assert row["payload"]["resume_metadata"] == "[REDACTED]"
    assert raw_secret not in row["event"]["metadata"]["diagnostic"]


def test_write_jsonl_rejects_reference_only_inline_content_before_file_creation(
    tmp_path,
) -> None:
    target = tmp_path / "events.jsonl"
    recorder = EventRecorder("run-reference-only-export")
    recorder.emit(
        "agent_llm_stream_event",
        {
            "step_id": "draft",
            "stream_event": {"text": "raw-stream-content"},
        },
    )

    with pytest.raises(EventSecurePayloadRequiredError, match="cannot be exported"):
        recorder.write_jsonl(target)

    assert not target.exists()


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
def test_framework_event_record_history_without_occurrence_time_fails_closed(
    time_fields: dict[str, str],
) -> None:
    payload = {
        "schema_version": "newsroom.event_record.v1",
        "event_id": "evt-missing-framework-time",
        "run_id": "run-missing-framework-time",
        "event_type": "workflow_started",
        "payload": {},
        **time_fields,
    }

    with pytest.raises((KeyError, ValueError)):
        FrameworkEventRecord.from_dict(payload)


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
