from core.framework.agent_loop import AgentLoopStatus, AgentRunner, AgentSpec
from core.framework.llm import FakeLLMClient
from core.framework.tools import REDACTED_VALUE, ToolDefinition, ToolPolicy, ToolRegistry
from storage.conversation import LocalJsonConversationStore


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


def test_agent_runner_exports_tools_from_resolved_policy() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="artifact.load"), lambda args: args)
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search", "artifact.load"],
        tool_policy=ToolPolicy(
            allowed_tools=["memory.search", "artifact.load"],
            blocked_tools=["artifact.load"],
        ),
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is True
    assert [tool["name"] for tool in llm.requests[0].tools] == ["memory.search"]


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


def test_agent_runner_redacts_tool_observations_before_next_prompt() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: {"token": fake_secret, "safe": "visible"},
    )
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        _agent(),
        {"request": {"topic": "chips"}},
    )

    second_prompt = llm.requests[1].messages[1]["content"]
    assert result.success is True
    assert fake_secret not in second_prompt
    assert REDACTED_VALUE in second_prompt


def test_agent_runner_persists_conversation_when_store_is_provided(tmp_path) -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    store = LocalJsonConversationStore(tmp_path)
    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        conversation_store=store,
    ).run(
        _agent(),
        {"request": {"topic": "chips"}},
        conversation_id="conversation-1",
    )

    messages = store.read_messages("conversation-1")

    assert result.success is True
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].content == {"request": {"topic": "chips"}}
    assert messages[1].content["output"] == {"analysis_result": {"summary": "ok"}}
    assert messages[1].metadata["status"] == "accepted"
    assert store.get_summary("conversation-1") == "agent_id=analyst status=accepted iterations=1"
