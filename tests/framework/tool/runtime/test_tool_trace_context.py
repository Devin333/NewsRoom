from __future__ import annotations

from framework.events import TraceContext
from framework.tool import ToolCall, ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus


def test_tool_executor_events_and_records_include_trace_context() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.echo", input_schema={"required": ["message"]}),
        lambda args: {"message": args["message"]},
    )
    trace = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="trace-1",
        span_id="step:s1",
    ).child(span_id="tool-parent", step_id="s1")
    call = ToolCall(tool_name="sample.echo", arguments={"message": "hi"}, call_id="call-1")

    executor = ToolExecutor(registry, trace_context=trace)
    observation = executor.execute(call, ToolPolicy(allowed_tools=["sample.echo"]))

    event = executor.list_events()[0].to_dict()
    record = executor.list_records()[0].to_dict()

    assert observation.status == ToolStatus.SUCCEEDED
    assert event["trace_id"] == "trace-1"
    assert event["span_id"] == "tool:call-1"
    assert event["parent_span_id"] == "tool-parent"
    assert record["trace_id"] == "trace-1"
    assert record["span_id"] == "tool:call-1"
