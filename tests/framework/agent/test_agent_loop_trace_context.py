from __future__ import annotations

from framework.agent.loop.events import AgentLoopEventRecorder
from framework.agent.models import AgentLoopEventType
from framework.agent.models.trace import AgentLoopTrace
from framework.events import TraceContext, is_valid_span_id, is_valid_trace_id


def test_agent_loop_event_recorder_outputs_trace_fields() -> None:
    trace = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="1" * 32,
        span_id="2" * 16,
    )

    recorder = AgentLoopEventRecorder(agent_id="agent-1", trace_context=trace)
    event = recorder.emit(AgentLoopEventType.AGENT_STARTED)

    assert event["run_id"] == "run-1"
    assert is_valid_trace_id(event["trace_id"])
    assert is_valid_span_id(event["span_id"])
    assert event["parent_span_id"] == trace.span_id
    assert event["agent_id"] == "agent-1"


def test_agent_loop_trace_default_iteration_ids_are_w3c_compatible() -> None:
    trace = AgentLoopTrace(agent_id="agent-1")

    first = trace.start_iteration(
        1,
        feedback=None,
        tool_observation_count_before=0,
        tools_available=[],
    )
    second = trace.start_iteration(
        2,
        feedback="retry",
        tool_observation_count_before=1,
        tools_available=["sample.echo"],
    )

    assert is_valid_trace_id(trace.trace_id)
    assert is_valid_span_id(trace.root_span_id)
    assert first.trace_id == second.trace_id == trace.trace_id
    assert first.parent_span_id == second.parent_span_id == trace.root_span_id
    assert is_valid_span_id(first.span_id)
    assert is_valid_span_id(second.span_id)
    assert first.span_id != second.span_id
