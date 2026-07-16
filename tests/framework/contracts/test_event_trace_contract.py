from __future__ import annotations

import pytest

from framework.events import (
    Event,
    EventBus,
    EventEnvelope,
    EventSubscriberError,
    TraceContext,
    W3CTracePropagator,
    trace_fields,
)


def test_event_trace_contract_envelope_round_trip_and_subscriber_failure() -> None:
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

    def _boom(envelope: EventEnvelope) -> None:
        raise RuntimeError("subscriber failed")

    bus.subscribe(_boom)
    with pytest.raises(EventSubscriberError) as caught:
        bus.publish(envelope)

    restored_envelope = EventEnvelope.from_dict(envelope.to_dict())
    assert restored_envelope.trace_id == "trace-events"
    assert restored_envelope.span_id == "step:s1"
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_trace_compatibility_facade_preserves_w3c_and_business_field_contract() -> None:
    metadata = {"nested": {"accepted": ["value"]}}
    context = TraceContext.root(
        run_id="run-trace-contract",
        workflow_id="wf-trace-contract",
        metadata=metadata,
    ).child(
        step_id="step-trace-contract",
        agent_id="agent-trace-contract",
        tool_call_id="tool-trace-contract",
        memory_operation_id="memory-trace-contract",
        artifact_id="artifact-trace-contract",
    )
    serialized = context.to_dict(redact=False)
    restored = TraceContext.from_dict(serialized)

    metadata["nested"]["accepted"].append("late-mutation")
    fields = trace_fields(restored)
    carrier = W3CTracePropagator().inject(restored)

    assert restored.is_injectable is True
    assert serialized["metadata"] == {"nested": {"accepted": ["value"]}}
    assert fields["agent_id"] == "agent-trace-contract"
    assert fields["tool_call_id"] == "tool-trace-contract"
    assert fields["memory_operation_id"] == "memory-trace-contract"
    assert fields["artifact_id"] == "artifact-trace-contract"
    assert carrier["traceparent"] == (
        f"00-{restored.trace_id}-{restored.span_id}-{restored.trace_flags}"
    )
