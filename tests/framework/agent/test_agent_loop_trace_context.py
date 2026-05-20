from __future__ import annotations

from framework.agent.loop.events import AgentLoopEventRecorder
from framework.agent.models import AgentLoopEventType
from framework.events import TraceContext


def test_agent_loop_event_recorder_outputs_trace_fields() -> None:
    trace = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="trace-1",
        span_id="step:s1",
    )

    recorder = AgentLoopEventRecorder(agent_id="agent-1", trace_context=trace)
    event = recorder.emit(AgentLoopEventType.AGENT_STARTED)

    assert event["run_id"] == "run-1"
    assert event["trace_id"] == "trace-1"
    assert event["span_id"] == "agent:agent-1"
    assert event["parent_span_id"] == "step:s1"
    assert event["agent_id"] == "agent-1"
