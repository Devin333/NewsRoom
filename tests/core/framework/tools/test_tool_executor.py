from core.framework.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            description="Search local memory",
            input_schema={"required": ["query"]},
        ),
        lambda args: {"matches": [{"title": args["query"], "score": 1.0}]},
    )
    return registry


def test_tool_executor_runs_allowed_tool_and_returns_observation() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "chip exports"},
            requested_by_agent_id="analyst",
            call_id="call-1",
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.call.call_id == "call-1"
    assert observation.result.output["matches"][0]["title"] == "chip exports"
    assert observation.elapsed_ms >= 0


def test_tool_executor_blocks_disallowed_tool() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "chip exports"},
            requested_by_agent_id="writer",
        ),
        ToolPolicy(allowed_tools=[]),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert observation.result.error_type == "ToolPermissionError"


def test_tool_executor_fails_missing_required_arguments() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(tool_name="memory.search", arguments={}, requested_by_agent_id="analyst"),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolRuntimeError"
    assert "missing required arguments" in (observation.result.error_message or "")
