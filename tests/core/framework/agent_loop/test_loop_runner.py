from core.framework.agent_loop import AgentLoopStatus, AgentRunner, AgentSpec
from core.framework.llm import FakeLLMClient
from core.framework.tools import ToolDefinition, ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: {"matches": [{"title": args["query"], "source": "fixture"}]},
    )
    return registry


def _agent() -> AgentSpec:
    return AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
    )


def test_agent_runner_handles_tool_call_judge_retry_and_final_output() -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"final_output","output":{"wrong_key":{"summary":"missing"}}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": "chips"}},
    )

    assert result.success is True
    assert result.status == AgentLoopStatus.ACCEPTED
    assert result.output == {"analysis_result": {"summary": "ok"}}
    assert result.metrics.llm_calls == 3
    assert result.metrics.tool_calls == 1
    assert result.metrics.token_usage.total_tokens == 60
    assert [event["event_type"] for event in result.events] == [
        "agent_started",
        "llm_call",
        "tool_call",
        "tool_observation",
        "llm_call",
        "judge_retry",
        "llm_call",
        "final_output",
    ]


def test_agent_runner_returns_retry_exhausted_after_invalid_outputs() -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"final_output","output":{"wrong_key":{}}}',
            '{"action_type":"final_output","output":{"wrong_key":{}}}',
            '{"action_type":"final_output","output":{"wrong_key":{}}}',
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": "chips"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.RETRY_EXHAUSTED
    assert result.metrics.llm_calls == 3
    assert result.verdict is not None
    assert result.verdict.missing_output_keys == ["analysis_result"]


def test_agent_runner_blocks_secret_like_final_output() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"final_output","output":{"analysis_result":{"secret":"'
                + fake_secret
                + '"}}}'
            ),
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": "chips"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.BLOCKED
    assert result.error == "output contains secret-like content"
