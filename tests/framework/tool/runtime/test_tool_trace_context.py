from __future__ import annotations

from framework.events import TraceContext, is_valid_span_id, is_valid_trace_id
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
        trace_id="1" * 32,
        span_id="2" * 16,
    )
    call = ToolCall(tool_name="sample.echo", arguments={"message": "hi"}, call_id="call-1")

    executor = ToolExecutor(registry, trace_context=trace)
    observation = executor.execute(call, ToolPolicy(allowed_tools=["sample.echo"]))

    event = executor.list_events()[0].to_dict()
    record = executor.list_records()[0].to_dict()

    assert observation.status == ToolStatus.SUCCEEDED
    assert is_valid_trace_id(event["trace_id"])
    assert is_valid_span_id(event["span_id"])
    assert event["parent_span_id"] == trace.span_id
    assert event["tool_call_id"] == "call-1"
    assert record["trace_id"] == event["trace_id"]
    assert record["span_id"] == event["span_id"]
    assert record["parent_span_id"] == event["parent_span_id"]
    assert observation.result.trace_id == event["trace_id"]
    assert observation.result.span_id == event["span_id"]
    assert observation.result.parent_span_id == event["parent_span_id"]
