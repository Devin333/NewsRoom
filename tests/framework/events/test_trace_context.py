from __future__ import annotations

from datetime import UTC, datetime

from framework.events import Event, EventEnvelope, EventRecord, EventRecorder, TraceContext, TraceEvent
from framework.events.trace import redact_trace_payload


def test_trace_context_root_child_and_round_trip() -> None:
    root = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="trace-1",
        span_id="workflow:run-1",
        metadata={"api_key": "secret", "safe": "visible"},
    )
    child = root.child(span_id="step:s1", step_id="s1")

    assert child.trace_id == "trace-1"
    assert child.parent_span_id == "workflow:run-1"
    assert child.step_id == "s1"
    assert child.to_dict()["metadata"]["api_key"] == "[REDACTED]"
    assert TraceContext.from_dict(child.to_dict()).span_id == "step:s1"


def test_trace_event_round_trip_and_redaction() -> None:
    context = TraceContext.root(run_id="run-1", trace_id="trace-1", span_id="root")
    event = TraceEvent(
        event_id="evt-1",
        event_type="step_started",
        timestamp=datetime(2026, 5, 20, 1, 2, tzinfo=UTC),
        context=context,
        component="workflow",
        operation="step",
        status="started",
        payload={"token": "secret"},
    )

    payload = event.to_dict()
    restored = TraceEvent.from_dict(payload)

    assert payload["payload"]["token"] == "[REDACTED]"
    assert restored.context.trace_id == "trace-1"
    assert restored.timestamp == datetime(2026, 5, 20, 1, 2, tzinfo=UTC)


def test_event_envelope_and_legacy_record_include_trace_fields() -> None:
    context = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="trace-1",
        span_id="root",
    ).child(span_id="step:s1", step_id="s1")
    event = Event(
        "step_started",
        run_id=context.run_id,
        trace_id=context.trace_id,
        span_id=context.span_id,
        parent_span_id=context.parent_span_id,
        workflow_id=context.workflow_id,
        step_id=context.step_id,
        component="workflow",
    )
    envelope = EventEnvelope(event=event, event_id="evt-1")

    recorder = EventRecorder("run-1", trace_context=context)
    record = recorder.emit("step_started", {"ok": True})

    assert envelope.to_dict()["trace_id"] == "trace-1"
    assert EventEnvelope.from_dict(envelope.to_dict()).span_id == "step:s1"
    assert record.to_dict()["parent_span_id"] == "root"
    assert EventRecord.from_dict(record.to_dict()).trace_id == "trace-1"


def test_redact_trace_payload_redacts_secret_like_keys() -> None:
    payload = {"nested": {"authorization": "Bearer secret"}, "safe": "ok"}

    assert redact_trace_payload(payload) == {
        "nested": {"authorization": "[REDACTED]"},
        "safe": "ok",
    }
