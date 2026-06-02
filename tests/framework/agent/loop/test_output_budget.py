from __future__ import annotations

import json

from framework.agent.loop import (
    AgentLoop,
    AgentOutputBudget,
    measure_agent_output,
    validate_agent_output_budget,
)
from framework.agent.models import AgentLoopStatus, AgentSpec
from framework.llm import FakeLLMClient
from framework.tool import ToolExecutor, ToolRegistry


def test_output_budget_measures_payload_without_recursive_traversal() -> None:
    payload: dict[str, object] = {}
    current = payload
    for _ in range(30):
        child: dict[str, object] = {}
        current["child"] = child
        current = child
    current["value"] = "done"

    measurement = measure_agent_output(payload)
    check = validate_agent_output_budget(
        payload,
        budget=AgentOutputBudget(max_depth=12, max_collection_items=100),
    )

    assert measurement.max_depth > 12
    assert check.has_violations is True
    assert check.violations[0].code == "agent.output.max_depth"


def test_output_budget_detects_collection_and_string_limits() -> None:
    payload = {
        "items": list(range(8)),
        "note": "x" * 20,
    }

    check = validate_agent_output_budget(
        payload,
        budget=AgentOutputBudget(
            max_json_bytes=1_000,
            max_depth=10,
            max_collection_items=5,
            max_string_bytes=10,
        ),
    )

    assert {violation.code for violation in check.violations} == {
        "agent.output.max_collection_items",
        "agent.output.max_string_bytes",
    }


def test_agent_loop_blocks_oversized_output_before_normalizer() -> None:
    normalizer_called = False

    def raising_normalizer(*, agent, output, inputs):
        nonlocal normalizer_called
        normalizer_called = True
        raise AssertionError("normalizer must not run for over-budget output")

    agent = AgentSpec(
        agent_id="budgeted-agent",
        name="Budgeted Agent",
        instructions="Return JSON.",
        validation_policy={
            "output_budget": {
                "max_json_bytes": 120,
                "max_depth": 10,
                "max_collection_items": 100,
                "max_string_bytes": 60,
            }
        },
    )
    llm = FakeLLMClient(
        [
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "x" * 100}},
                }
            )
        ]
    )

    result = AgentLoop(
        llm_client=llm,
        tool_executor=ToolExecutor(ToolRegistry()),
        output_normalizer=raising_normalizer,
    ).run(agent, {"topic": "budget"}, [], run_id="run-budget")

    assert normalizer_called is False
    assert result.success is False
    assert result.status == AgentLoopStatus.BLOCKED
    assert result.verdict is not None
    assert result.verdict.policy_violations[0].startswith("agent output string bytes exceeded")
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason.value == "judge_blocked"
