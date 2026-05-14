from core.framework.agent_loop import (
    AgentLoopPolicy,
    AgentLoopStatus,
    AgentLoopStopReason,
    AgentRunner,
    AgentSpec,
)
from core.framework.llm import (
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMResponse,
    LLMRequest,
    LLMStreamEvent,
    TokenUsage,
)
from core.framework.tools import (
    REDACTED_VALUE,
    ToolDefinition,
    ToolPolicy,
    ToolRegistry,
    register_control_tools,
)
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
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.FINAL_OUTPUT_ACCEPTED
    assert result.trace["summary"]["judge_retry_count"] == 1
    assert [event["event_type"] for event in result.events] == [
        "agent_started",
        "iteration_started",
        "llm_call",
        "action_parsed",
        "tool_call",
        "tool_observation",
        "iteration_started",
        "llm_call",
        "action_parsed",
        "judge_retry",
        "iteration_started",
        "llm_call",
        "action_parsed",
        "judge_accept",
        "final_output",
        "agent_completed",
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
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.JUDGE_RETRY_EXHAUSTED
    assert result.diagnostics.healthy is False
    assert result.diagnostics.issues[0].code == "judge_retry_exhausted"


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


def test_writer_agent_cannot_fetch_even_when_policy_allows_fetch_tool() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="source.fetch_url", input_schema={"required": ["url"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1) or {"content": "raw"},
    )
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call","tool_name":"source.fetch_url",'
                '"tool_args":{"url":"https://example.com/raw"}}'
            )
        ]
    )
    agent = AgentSpec(
        agent_id="writer",
        name="WriterAgent",
        role="Write",
        goal="Write only from provided evidence",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="final_report",
        allowed_tools=["source.fetch_url"],
        loop_policy=AgentLoopPolicy(max_iterations=1),
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    observations = [
        event["observation"]
        for event in result.events
        if event["event_type"] == "tool_observation"
    ]
    assert llm.requests[0].tools == []
    assert calls["count"] == 0
    assert result.metrics.tool_blocks == 1
    assert observations[0]["status"] == "blocked"
    assert "not allowed" in observations[0]["result"]["error_message"]


def test_agent_runner_blocks_tool_call_after_agent_budget_is_exhausted() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1)
        or {"matches": [{"title": args["query"]}]},
    )
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"a"}}',
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"b"}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
        tool_policy=ToolPolicy(
            allowed_tools=["memory.search"],
            max_tool_calls_per_agent=1,
        ),
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    tool_observations = [
        event["observation"]
        for event in result.events
        if event["event_type"] == "tool_observation"
    ]
    assert result.success is True
    assert calls["count"] == 1
    assert result.metrics.tool_blocks == 1
    assert [observation["status"] for observation in tool_observations] == [
        "succeeded",
        "blocked",
    ]
    assert "max_tool_calls_per_agent" in tool_observations[1]["summary"]
    assert result.diagnostics is not None
    assert result.diagnostics.trace_summary["tool_status_counts"]["blocked"] == 1


def test_agent_runner_accepts_control_set_output_tool_result() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call","tool_name":"control.set_output",'
                '"tool_args":{"output":{"analysis_result":{"summary":"ok"}}}}'
            )
        ]
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["control.set_output"],
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is True
    assert result.status == AgentLoopStatus.ACCEPTED
    assert result.output == {"analysis_result": {"summary": "ok"}}
    assert result.metrics.llm_calls == 1
    assert result.metrics.tool_calls == 1
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.CONTROL_OUTPUT_ACCEPTED
    assert [event["event_type"] for event in result.events] == [
        "agent_started",
        "iteration_started",
        "llm_call",
        "action_parsed",
        "tool_call",
        "tool_observation",
        "judge_accept",
        "final_output",
        "agent_completed",
    ]
    final_output_events = [
        event for event in result.events if event["event_type"] == "final_output"
    ]
    assert final_output_events[-1]["via_tool"] == "control.set_output"


def test_agent_runner_carries_llm_route_manifest_into_events_and_trace() -> None:
    llm = FakeLLMClient(
        [
            LLMResponse(
                content='{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
                usage=TokenUsage(input_tokens=10, output_tokens=4),
                metadata={
                    "provider": "test",
                    "model": "model-b",
                    "llm_route_id": "writer",
                    "llm_deployment_id": "fallback",
                    "llm_fallback_used": True,
                    "llm_fallback_count": 1,
                    "llm_router_event_count": 7,
                    "llm_provider_resolution_trace": [
                        {"source": "agent_task_route", "matched": True, "route_id": "writer"}
                    ],
                    "llm_route_manifest": {
                        "schema_version": "newsroom.llm_route_manifest.v1",
                        "status": "succeeded",
                        "fallback_count": 1,
                    },
                },
            )
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": "chips"}},
    )

    llm_event = next(event for event in result.events if event["event_type"] == "llm_call")
    llm_trace = result.trace["iterations"][0]["llm_call"]

    assert llm_event["route_id"] == "writer"
    assert llm_event["deployment_id"] == "fallback"
    assert llm_event["fallback_used"] is True
    assert llm_event["fallback_count"] == 1
    assert llm_event["router_event_count"] == 7
    assert llm_trace["route_manifest"]["schema_version"] == "newsroom.llm_route_manifest.v1"
    assert llm_trace["provider_resolution_trace"][0]["source"] == "agent_task_route"


def test_agent_runner_consumes_llm_stream_and_records_stream_events() -> None:
    class StreamingLLM:
        def __init__(self) -> None:
            self.requests: list[LLMRequest] = []

        def complete(self, request: LLMRequest) -> LLMResponse:
            raise AssertionError("streaming path should not call complete")

        def stream(self, request: LLMRequest):
            self.requests.append(request)
            yield LLMStreamEvent(event_type="message_start", metadata={"provider": "fake"})
            yield LLMStreamEvent(
                event_type="text_delta",
                text_delta='{"action_type":"final_output","output":',
            )
            yield LLMStreamEvent(
                event_type="text_delta",
                text_delta='{"analysis_result":{"summary":"ok"}}}',
            )
            yield LLMStreamEvent(
                event_type="usage_delta",
                usage_delta=TokenUsage(input_tokens=5, output_tokens=7),
            )
            yield LLMStreamEvent(event_type="message_complete", metadata={"finish_reason": "stop"})

    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(llm_streaming_enabled=True),
    )

    result = AgentRunner(llm_client=StreamingLLM(), tool_registry=_registry()).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    stream_events = [
        event for event in result.events if event["event_type"] == "llm_stream_event"
    ]

    assert result.success is True
    assert result.output == {"analysis_result": {"summary": "ok"}}
    assert result.metrics.llm_calls == 1
    assert result.metrics.llm_stream_event_count == 5
    assert result.metrics.token_usage.total_tokens == 12
    assert [event["sequence"] for event in stream_events] == [1, 2, 3, 4, 5]
    assert stream_events[1]["stream_event_type"] == "text_delta"
    assert stream_events[1]["text_delta_chars"] == 39
    assert result.trace["iterations"][0]["llm_call"]["response_chars"] > 0


def test_agent_runner_blocks_before_llm_call_when_global_budget_is_exhausted() -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"final_output","output":{"wrong_key":{"summary":"missing"}}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=1))

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        global_budget_tracker=tracker,
    ).run(_agent(), {"request": {"topic": "chips"}})

    assert result.success is False
    assert result.status == AgentLoopStatus.BLOCKED
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.GLOBAL_BUDGET_EXCEEDED
    assert result.metrics.llm_calls == 1
    assert result.metrics.global_budget_check["violations"] == ["max_llm_calls"]
    assert llm.call_count == 1


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
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.SECRET_BLOCKED
    assert result.diagnostics.severity.value == "blocked"


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


def test_agent_runner_reports_parser_retry_diagnostics() -> None:
    llm = FakeLLMClient(["not-json", "still-not-json"])
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(max_iterations=4, max_parser_errors=1),
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.RETRY_EXHAUSTED
    assert result.metrics.parser_errors == 2
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.PARSER_RETRY_EXHAUSTED
    assert result.diagnostics.issues[0].code == "parser_retry_exhausted"
    assert result.trace["summary"]["parser_error_count"] == 2


def test_agent_runner_stalls_on_repeated_tool_call_signature() -> None:
    registry = _registry()
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
        ]
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
        loop_policy=AgentLoopPolicy(max_iterations=5, max_repeated_tool_calls=2),
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.STALLED
    assert result.metrics.repeated_tool_calls == 2
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.REPEATED_TOOL_CALL_STALLED
    assert result.diagnostics.repeated_tool_calls == 1
    assert result.diagnostics.issues[0].code == "repeated_tool_call"


def test_agent_runner_waits_for_tool_approval_with_diagnostics() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="report.publish",
            side_effect="publishing",
            requires_approval=True,
        ),
        lambda args: {"published": True},
    )
    llm = FakeLLMClient(
        ['{"action_type":"tool_call","tool_name":"report.publish","tool_args":{"report_id":"r1"}}']
    )
    agent = AgentSpec(
        agent_id="publisher",
        name="Publisher",
        role="Publish",
        goal="Publish report",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="publish_result",
        allowed_tools=["report.publish"],
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"report_id": "r1"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.WAITING_FOR_APPROVAL
    assert result.metrics.tool_approval_requests == 1
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.TOOL_APPROVAL_REQUIRED
    assert result.diagnostics.issues[0].tool_name == "report.publish"
    assert result.events[-1]["event_type"] == "agent_waiting_for_approval"


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
    assert [message.role for message in messages] == ["user", "diagnostic", "assistant"]
    assert messages[0].content == {"request": {"topic": "chips"}}
    assert messages[1].metadata["message_type"] == "agent_loop_diagnostics"
    assert messages[1].content["diagnostics"]["stop_reason"] == "final_output_accepted"
    assert messages[2].content["output"] == {"analysis_result": {"summary": "ok"}}
    assert messages[2].metadata["status"] == "accepted"
    assert store.get_summary("conversation-1") == (
        "agent_id=analyst status=accepted iterations=1 "
        "stop_reason=final_output_accepted"
    )


def test_agent_runner_persists_tool_and_judge_events_to_conversation(tmp_path) -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"final_output","output":{"wrong_key":{"summary":"missing"}}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    store = LocalJsonConversationStore(tmp_path)

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        conversation_store=store,
    ).run(
        _agent(),
        {"request": {"topic": "chips"}},
        conversation_id="conversation-events",
    )

    messages = store.read_messages("conversation-events")

    assert result.success is True
    assert [message.role for message in messages] == [
        "user",
        "tool",
        "judge",
        "diagnostic",
        "assistant",
    ]
    assert messages[1].metadata == {
        "message_type": "agent_tool_observation",
        "event_type": "tool_observation",
        "tool_name": "memory.search",
        "tool_call_id": messages[1].content["tool_call_id"],
        "status": "succeeded",
    }
    assert messages[1].content["tool_name"] == "memory.search"
    assert messages[1].content["result"]["output"]["matches"][0]["title"] == "chips"
    assert messages[2].role == "judge"
    assert messages[2].content["feedback"] == "missing output keys: analysis_result"
    assert messages[2].content["verdict"]["decision"] == "retry"
    assert messages[3].metadata["message_type"] == "agent_loop_diagnostics"
    assert messages[3].content["trace_summary"]["judge_retry_count"] == 1
    assert messages[4].content["output"] == {"analysis_result": {"summary": "ok"}}
