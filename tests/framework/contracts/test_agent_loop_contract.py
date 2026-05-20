from __future__ import annotations

import json

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec
from framework.llm import FakeLLMClient
from framework.tool import ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry


def test_agent_loop_contract_records_tool_trajectory() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="contract.lookup",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        lambda args: {"answer": f"found {args['query']}"},
    )
    agent = AgentSpec(
        agent_id="contract-agent",
        name="Contract Agent",
        instructions="Use the tool then answer.",
        allowed_tools=["contract.lookup"],
        loop_policy=AgentLoopPolicy(max_iterations=3),
        tool_policy=ToolPolicy(
            allowed_tools=["contract.lookup"],
            require_explicit_allowlist=True,
            require_approval_for_side_effects=False,
        ),
    )
    llm = FakeLLMClient(
        [
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "contract.lookup",
                    "tool_args": {"query": "trace"},
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

    result = AgentLoop(llm_client=llm, tool_executor=ToolExecutor(registry)).run(
        agent,
        {"topic": "trace"},
        registry.export_schema_for_llm(agent.agent_id, agent.resolved_tool_policy()),
        run_id="run-agent-contract",
    )

    assert result.success is True
    assert result.termination_reason == "final_output_accepted"
    assert result.max_steps_reached is False
    assert result.trajectory[0]["parsed_action"]["action_type"] == "tool_call"
    assert result.trajectory[0]["tool_calls"][0]["tool_name"] == "contract.lookup"
    assert result.trajectory[0]["observations"][0]["status"] == "succeeded"
    assert result.tool_calls[0]["tool_name"] == "contract.lookup"
