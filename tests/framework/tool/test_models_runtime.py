from __future__ import annotations

from framework.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)


def test_tool_definition_and_call_prd_aliases() -> None:
    definition = ToolDefinition.from_dict(
        {
            "name": "sample.echo",
            "description": "Echo",
            "input_schema": {"required": ["message"]},
            "side_effect": "read_only",
        }
    )
    call = ToolCall.new("sample.echo", {"message": "hi"}, requested_by="agent-1")

    assert definition.namespace == "sample"
    assert definition.short_name() == "echo"
    assert call.requested_by == "agent-1"
    assert call.requested_by_agent_id == "agent-1"


def test_tool_executor_returns_success_result() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.echo", input_schema={"required": ["message"]}),
        lambda args: {"message": args["message"]},
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.echo", arguments={"message": "hello"}),
        ToolPolicy(allowed_tools=["sample.echo"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.ok is True
    assert observation.result.output == {"message": "hello"}
