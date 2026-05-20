from __future__ import annotations

import json

import pytest

from framework.events import Event, EventBus, EventEnvelope, EventRecorder, TraceContext


def test_event_trace_contract_envelope_record_jsonl_and_subscriber_failure(tmp_path) -> None:
    context = TraceContext.root(
        run_id="run-events-contract",
        workflow_id="wf",
        trace_id="trace-events",
        span_id="workflow:run-events-contract",
    ).child(span_id="step:s1", step_id="s1")
    envelope = EventEnvelope(
        event=Event(
            "step_started",
            run_id=context.run_id,
            trace_id=context.trace_id,
            span_id=context.span_id,
            parent_span_id=context.parent_span_id,
            workflow_id=context.workflow_id,
            step_id=context.step_id,
        ),
        event_id="evt-1",
    )
    bus = EventBus()
    recorder = EventRecorder("run-events-contract", event_bus=bus, trace_context=context)

    def _boom(envelope: EventEnvelope) -> None:
        raise RuntimeError("subscriber failed")

    bus.subscribe(_boom)
    with pytest.raises(RuntimeError):
        recorder.emit("step_started", {"ok": True})

    restored_envelope = EventEnvelope.from_dict(envelope.to_dict())
    path = recorder.write_jsonl(tmp_path / "events.jsonl")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert restored_envelope.trace_id == "trace-events"
    assert lines[0]["trace_id"] == "trace-events"
    assert lines[0]["span_id"] == "step:s1"
