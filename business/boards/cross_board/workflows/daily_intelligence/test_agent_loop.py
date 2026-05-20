from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework import RunResult, WorkflowRunner
from framework.workflow import DataBuffer
from framework.agent import AgentRunner, AgentSpec
from framework.llm import FakeLLMClient
from framework.specs import StepSpec, WorkflowSpec
from framework.tool import ToolDefinition, ToolRegistry
from framework.workflow import FunctionStepRegistry, ScopedDataBuffer

PROFILE = "test-agent-loop"
WORKFLOW_ID = "daily-intelligence-test-agent-loop"
WORKFLOW_VERSION = "0.1.0"


def build_test_agent_loop_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WORKFLOW_ID,
        name="Daily Intelligence Test AgentLoop",
        version=WORKFLOW_VERSION,
        description="Deterministic FakeLLM + fake tool AgentLoop regression workflow.",
        start_step_id="run_agent",
        terminal_step_ids=["run_agent"],
        steps=[
            StepSpec(
                step_id="run_agent",
                name="Run deterministic AgentLoop",
                implementation="daily_test_agent_loop.run_agent",
                read_keys=["request"],
                write_keys=[
                    "analysis_result",
                    "agent_loop_result",
                    "agent_loop_events",
                    "agent_loop_metrics",
                    "agent_loop_diagnostics",
                    "agent_loop_trace",
                ],
                required_output_keys=[
                    "analysis_result",
                    "agent_loop_result",
                    "agent_loop_events",
                    "agent_loop_metrics",
                    "agent_loop_diagnostics",
                    "agent_loop_trace",
                ],
            )
        ],
        metadata={"profile": PROFILE, "product_path": False},
    )


def build_test_agent_loop_registry() -> FunctionStepRegistry:
    registry = FunctionStepRegistry()
    registry.register("daily_test_agent_loop.run_agent", _run_agent_step)
    return registry


def run_test_agent_loop(
    *,
    artifact_root: str | Path,
    request: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> RunResult:
    runner = WorkflowRunner(
        artifact_root=artifact_root,
        function_registry=build_test_agent_loop_registry(),
    )
    return runner.run(
        build_test_agent_loop_workflow(),
        request or {"topic": "daily intelligence agent loop smoke"},
        profile=PROFILE,
        run_id=run_id,
    )


def _run_agent_step(buffer: ScopedDataBuffer) -> dict[str, Any]:
    request = buffer.read("request")
    topic = str(request.get("topic") or "daily intelligence agent loop smoke")
    agent = AgentSpec(
        agent_id="test_analyst",
        name="Test Analyst",
        role="AnalystAgent",
        goal=f"Analyze deterministic fixture context for {topic}",
        instructions="Use allowed tools only and return JSON actions.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
    )
    result = AgentRunner(
        llm_client=_build_fake_llm(topic),
        tool_registry=_build_fake_tool_registry(),
    ).run(agent, {"request": request})

    if not result.success:
        raise RuntimeError(result.error or f"AgentLoop did not succeed: {result.status.value}")

    return {
        "analysis_result": result.output["analysis_result"],
        "agent_loop_result": result.to_dict(),
        "agent_loop_events": result.events,
        "agent_loop_metrics": result.metrics.to_dict(),
        "agent_loop_diagnostics": result.diagnostics.to_dict() if result.diagnostics else None,
        "agent_loop_trace": result.trace,
    }


def _build_fake_llm(topic: str) -> FakeLLMClient:
    return FakeLLMClient(
        [
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "memory.search",
                    "tool_args": {"query": topic},
                },
                sort_keys=True,
            ),
            json.dumps(
                {"action_type": "final_output", "output": {"wrong_key": {"summary": "missing"}}},
                sort_keys=True,
            ),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {
                        "analysis_result": {
                            "summary": f"Deterministic AgentLoop analysis for {topic}.",
                            "tool_used": "memory.search",
                            "confidence": "high",
                        }
                    },
                },
                sort_keys=True,
            ),
        ]
    )


def _build_fake_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            description="Fake local memory search for AgentLoop regression tests.",
            input_schema={"required": ["query"]},
        ),
        lambda args: {
            "matches": [
                {
                    "title": f"Fixture memory for {args['query']}",
                    "source": "fixture://agent-loop",
                    "score": 1.0,
                }
            ]
        },
    )
    return registry


def test_agent_loop_smoke_workflow(tmp_path) -> None:
    buffer = DataBuffer({"request": {"topic": "agentic research"}})
    output = _run_agent_step(
        buffer.scope(
            read_keys=["request"],
            write_keys=[
                "analysis_result",
                "agent_loop_result",
                "agent_loop_events",
                "agent_loop_metrics",
                "agent_loop_diagnostics",
                "agent_loop_trace",
            ],
        )
    )

    assert output["analysis_result"]["confidence"] == "high"
    assert output["agent_loop_metrics"]["llm_calls"] == 3
    assert output["agent_loop_metrics"]["tool_calls"] == 1
    assert output["agent_loop_diagnostics"]["stop_reason"] == "final_output_accepted"
    assert output["agent_loop_trace"]["summary"]["judge_retry_count"] == 1

