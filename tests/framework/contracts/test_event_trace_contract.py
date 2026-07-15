from __future__ import annotations

import pytest

from framework.events import (
    Event,
    EventBus,
    EventEnvelope,
    EventSubscriberError,
    TraceContext,
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
