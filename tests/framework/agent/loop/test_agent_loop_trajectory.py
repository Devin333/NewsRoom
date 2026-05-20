from __future__ import annotations

import json

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec
from framework.llm import FakeLLMClient
from framework.tool import ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry


def test_agent_loop_result_contains_standard_trajectory_with_tool_observation() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.lookup",
            description="lookup",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        lambda arguments: {"answer": f"found {arguments['query']}"},
    )
    llm = FakeLLMClient(
        [
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "test.lookup",
                    "tool_args": {"query": "agent memory"},
                }
            ),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done"}},
                }
            ),
        ]
    )
    agent = AgentSpec(
        agent_id="agent-trajectory",
        name="Trajectory Agent",
        instructions="Use a tool then answer.",
        allowed_tools=["test.lookup"],
        loop_policy=AgentLoopPolicy(max_iterations=3),
        tool_policy=ToolPolicy(
            allowed_tools=["test.lookup"],
            require_explicit_allowlist=True,
            require_approval_for_side_effects=False,
        ),
    )

    result = AgentLoop(
        llm_client=llm,
        tool_executor=ToolExecutor(registry),
    ).run(
        agent,
        {"topic": "agent memory"},
        registry.export_schema_for_llm(agent.agent_id, agent.resolved_tool_policy()),
        run_id="run-trajectory",
    )

    payload = result.to_dict()
    assert result.success is True
    assert payload["termination_reason"] == "final_output_accepted"
    assert payload["max_steps_reached"] is False
    assert len(payload["trajectory"]) == 2
    first = payload["trajectory"][0]
    assert first["iteration"] == 1
    assert first["duration_ms"] is not None
    assert first["parsed_action"]["action_type"] == "tool_call"
    assert first["llm_request_ref"] == "agent-trajectory:llm_call:1"
    assert first["tool_calls"][0]["tool_name"] == "test.lookup"
    assert first["observations"][0]["status"] == "succeeded"
    assert result.tool_calls[0]["tool_name"] == "test.lookup"
