from __future__ import annotations

import json

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec, AgentLoopResult
from framework.llm import FakeLLMClient
from framework.tool import ToolExecutor, ToolRegistry


def test_agent_loop_records_final_termination_reason() -> None:
    result = _run_agent_with_responses(
        [
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "ok"}},
                }
            )
        ],
        max_iterations=2,
    )

    payload = result.to_dict()
    assert payload["termination_reason"] == "final_output_accepted"
    assert payload["max_steps_reached"] is False
    assert payload["trajectory"][0]["decision"] == "accept"


def test_agent_loop_marks_max_steps_reached() -> None:
    result = _run_agent_with_responses(
        [
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "missing.tool",
                    "tool_args": {},
                }
            )
        ],
        max_iterations=1,
    )

    payload = result.to_dict()
    assert result.success is False
    assert payload["termination_reason"] == "max_iterations_exceeded"
    assert payload["max_steps_reached"] is True
    assert payload["trajectory"][0]["parsed_action"]["action_type"] == "tool_call"


def _run_agent_with_responses(
    responses: list[str],
    *,
    max_iterations: int,
) -> AgentLoopResult:
    registry = ToolRegistry()
    agent = AgentSpec(
        agent_id="agent-termination",
        name="Termination Agent",
        instructions="Answer.",
        loop_policy=AgentLoopPolicy(max_iterations=max_iterations),
    )
    return AgentLoop(
        llm_client=FakeLLMClient(responses),
        tool_executor=ToolExecutor(registry),
    ).run(agent, {"topic": "x"}, [], run_id="run-termination", standalone=True)
