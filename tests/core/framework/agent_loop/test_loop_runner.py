from typing import Any

import pytest

from core.framework.agent_loop import (
    AgentLoopTrace,
    AgentLoopPolicy,
    AgentLoopStatus,
    AgentLoopStopReason,
    AgentRunner,
    AgentSpec,
    LocalSubAgentExecutor,
    SubAgentResult,
    SubAgentTask,
)
from framework.llm import (
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMResponse,
    LLMRequest,
    LLMStreamEvent,
    TokenUsage,
)
from framework.tool.builtin.control import register_control_tools
from framework.tool.models import ToolDefinition, ToolPolicy
from framework.tool.governance.redaction import REDACTED_VALUE
from framework.tool.registry import ToolRegistry
from core.framework.workers import InMemoryApprovalStore
from storage.conversation import (
    AgentIterationCheckpoint,
    ConversationCursor,
    LocalJsonConversationStore,
)


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
            '{"analysis_result":{"summary":"ok"}}',
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


def test_agent_runner_applies_injected_output_normalizer() -> None:
    def normalize_output(
        *,
        agent: AgentSpec,
        output: dict[str, Any],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        _ = inputs
        normalized = dict(output)
        normalized[agent.output_key] = {
            **dict(output.get(agent.output_key) or {}),
            "normalized": True,
        }
        return normalized

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
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        output_normalizer=normalize_output,
    ).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is True
    assert result.output == {"analysis_result": {"summary": "ok", "normalized": True}}


def test_agent_runner_excludes_blocked_tools_from_prompt_schema() -> None:
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


def test_agent_runner_blocks_tool_call_not_in_agent_allowlist() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="http.fetch", input_schema={"required": ["url"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1) or {"content": "raw"},
    )
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call","tool_name":"http.fetch",'
                '"tool_args":{"url":"https://example.com/raw"}}'
            )
        ]
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Analyze provided input",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
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


def test_agent_runner_allows_generic_fetch_tool_when_policy_allows_it() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="http.fetch", input_schema={"required": ["url"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1) or {"content": "raw"},
    )
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call","tool_name":"http.fetch",'
                '"tool_args":{"url":"https://example.com/raw"}}'
            ),
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    agent = AgentSpec(
        agent_id="collector",
        name="Collector",
        role="Collect",
        goal="Collect generic input",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["http.fetch"],
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
    assert [tool["name"] for tool in llm.requests[0].tools] == ["http.fetch"]
    assert llm.requests[0].tools[0]["input_schema"] == {"required": ["url"]}
    assert calls["count"] == 1
    assert result.success is True
    assert result.metrics.tool_blocks == 0
    assert observations[0]["status"] == "succeeded"


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


def test_agent_runner_records_redacted_llm_call_artifacts() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    llm = FakeLLMClient(
        [
            LLMResponse(
                content='{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
                usage=TokenUsage(input_tokens=4, output_tokens=6),
                metadata={"provider": "fake", "model": "fake-llm", "api_key": fake_secret},
            )
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": fake_secret}},
    )
    artifact = result.llm_call_artifacts[0].to_dict()

    assert result.success is True
    assert artifact["artifact_id"] == "analyst:llm_call:1"
    assert artifact["iteration"] == 1
    assert artifact["request"]["messages"][1]["content"].find(fake_secret) == -1
    assert artifact["response"]["metadata"]["api_key"] == REDACTED_VALUE
    assert artifact["metadata"]["provider"] == "fake"
    assert fake_secret not in str(result.to_dict()["llm_call_artifacts"])


def test_agent_loop_trace_records_replayable_redacted_call_refs() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    llm = FakeLLMClient(
        [
            LLMResponse(
                content='{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
                usage=TokenUsage(input_tokens=4, output_tokens=6),
                metadata={
                    "provider": "fake",
                    "model": "fake-llm",
                    "api_key": fake_secret,
                    "llm_call_id": "call-1",
                },
            )
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": fake_secret}},
    )
    iteration = result.trace["iterations"][0]
    restored = AgentLoopTrace.from_dict(result.trace)

    assert result.success is True
    assert iteration["prompt_hash"]
    assert iteration["llm_call_id"] == "call-1"
    assert iteration["llm_artifact_ref"] == "analyst:llm_call:1"
    assert iteration["parsed_action"]["action_type"] == "final_output"
    assert iteration["judge_result"]["decision"] == "accept"
    assert fake_secret not in str(result.trace)
    assert restored.to_dict() == result.trace


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


def test_agent_runner_uses_pointer_pattern_for_large_tool_observations() -> None:
    large_text = "x" * 400
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: {"items": [{"title": large_text} for _ in range(5)]},
    )
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
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
            max_result_chars_inline=120,
            spill_large_results_to_artifact=True,
        ),
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    observation = next(
        event["observation"]
        for event in result.events
        if event["event_type"] == "tool_observation"
    )
    prompt = llm.requests[1].messages[1]["content"]

    assert result.success is True
    assert observation["tool_call_id"]
    assert observation["tool_name"] == "memory.search"
    assert observation["status"] == "succeeded"
    assert observation["elapsed_ms"] >= 0
    assert observation["result"]["output"]["artifact_ref"]["artifact_id"].startswith(
        "tool_result:"
    )
    assert observation["result"]["output"]["count"] == 1
    assert "artifact_ref" in prompt
    assert large_text not in prompt


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


def test_agent_runner_reports_empty_output_retry_diagnostics() -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"final_output","output":{}}',
            '{"action_type":"final_output","output":{}}',
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
        loop_policy=AgentLoopPolicy(max_iterations=4, max_judge_retries=1),
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.RETRY_EXHAUSTED
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.EMPTY_OUTPUT_EXHAUSTED
    assert result.diagnostics.issues[0].code == "empty_output_exhausted"


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


def test_agent_runner_blocks_subagent_delegation_by_default() -> None:
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"citation_sanity_checker",'
                '"subagent_task":"check citations",'
                '"handoff_reason":"citation risk"}'
            )
        ]
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        _agent(),
        {"request": {"topic": "chips"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.BLOCKED
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.AGENT_POLICY_BLOCKED
    assert result.verdict is not None
    assert result.verdict.policy_violations == ["subagent delegation not allowed"]


def test_agent_runner_allows_listed_subagent_contract_without_orchestration() -> None:
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"citation_sanity_checker",'
                '"subagent_task":"check citations",'
                '"handoff_reason":"citation risk"}'
            ),
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    agent = AgentSpec(
        agent_id="writer",
        name="WriterAgent",
        role="Write",
        goal="Write report",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(allow_subagents=True),
        allowed_subagents=["citation_sanity_checker"],
    )

    result = AgentRunner(llm_client=llm, tool_registry=_registry()).run(
        agent,
        {"request": {"topic": "chips"}},
    )

    assert result.success is True
    assert result.output == {"analysis_result": {"summary": "ok"}}
    assert "(0," not in llm.requests[1].messages[1]["content"]
    assert "parent_agent_id=writer" in llm.requests[1].messages[1]["content"]
    assert "child_agent_id=citation_sanity_checker" in llm.requests[1].messages[1]["content"]
    assert "handoff_reason=citation risk" in llm.requests[1].messages[1]["content"]


def test_agent_runner_executes_allowed_subagent_and_returns_snapshot_feedback() -> None:
    class FakeSubAgentExecutor:
        def __init__(self) -> None:
            self.tasks: list[SubAgentTask] = []

        def run(self, task: SubAgentTask) -> SubAgentResult:
            self.tasks.append(task)
            return SubAgentResult(
                child_agent_id=task.child_agent_id,
                success=True,
                output={"citation_check": {"risk": "low"}},
                summary="citations look safe",
                metrics={"iterations": 1},
            )

    executor = FakeSubAgentExecutor()
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"citation_sanity_checker",'
                '"subagent_task":"check citations",'
                '"handoff_reason":"citation risk"}'
            ),
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    agent = AgentSpec(
        agent_id="writer",
        name="WriterAgent",
        role="Write",
        goal="Write report",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(allow_subagents=True),
        allowed_subagents=["citation_sanity_checker"],
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        subagent_executor=executor,
    ).run(agent, {"request": {"topic": "chips"}})

    assert result.success is True
    assert len(executor.tasks) == 1
    assert executor.tasks[0].parent_agent_id == "writer"
    assert executor.tasks[0].child_agent_id == "citation_sanity_checker"
    assert executor.tasks[0].inputs["parent_inputs"] == {"request": {"topic": "chips"}}
    assert [event["event_type"] for event in result.events if "subagent" in event["event_type"]] == [
        "subagent_delegation_requested",
        "subagent_completed",
    ]
    assert "subagent delegation completed" in llm.requests[1].messages[1]["content"]
    assert "citations look safe" in llm.requests[1].messages[1]["content"]
    assert "citation_check" in llm.requests[1].messages[1]["content"]


def test_local_subagent_executor_runs_child_agent_with_parent_snapshot() -> None:
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"citation_sanity_checker",'
                '"subagent_task":"check citations",'
                '"handoff_reason":"citation risk"}'
            ),
            '{"action_type":"final_output","output":{"citation_check":{"risk":"low"}}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    child = AgentSpec(
        agent_id="citation_sanity_checker",
        name="Citation Checker",
        role="Check citations",
        goal="Return citation risk",
        instructions="Return JSON actions only.",
        input_keys=["subagent_task", "parent_inputs"],
        output_key="citation_check",
    )
    parent = AgentSpec(
        agent_id="writer",
        name="WriterAgent",
        role="Write",
        goal="Write report",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(allow_subagents=True),
        allowed_subagents=["citation_sanity_checker"],
    )
    executor = LocalSubAgentExecutor(
        agents={"citation_sanity_checker": child},
        llm_client=llm,
        tool_registry=_registry(),
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        subagent_executor=executor,
    ).run(parent, {"request": {"topic": "chips"}})
    child_prompt = llm.requests[1].messages[1]["content"]
    parent_resume_prompt = llm.requests[2].messages[1]["content"]

    assert result.success is True
    assert result.output == {"analysis_result": {"summary": "ok"}}
    assert '"subagent_task": "check citations"' in child_prompt
    assert '"parent_agent_id": "writer"' in child_prompt
    assert '"parent_inputs": {"request": {"topic": "chips"}}' in child_prompt
    assert "subagent delegation completed" in parent_resume_prompt
    assert "citation_check" in parent_resume_prompt


def test_local_subagent_executor_disables_nested_delegation_by_default() -> None:
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"citation_sanity_checker",'
                '"subagent_task":"check citations"}'
            ),
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"nested_agent",'
                '"subagent_task":"nested work"}'
            ),
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"handled"}}}',
        ]
    )
    child = AgentSpec(
        agent_id="citation_sanity_checker",
        name="Citation Checker",
        role="Check citations",
        goal="Return citation risk",
        instructions="Return JSON actions only.",
        input_keys=["subagent_task", "parent_inputs"],
        output_key="citation_check",
        loop_policy=AgentLoopPolicy(allow_subagents=True),
        allowed_subagents=["nested_agent"],
    )
    parent = AgentSpec(
        agent_id="writer",
        name="WriterAgent",
        role="Write",
        goal="Write report",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(allow_subagents=True),
        allowed_subagents=["citation_sanity_checker"],
    )
    executor = LocalSubAgentExecutor(
        agents={"citation_sanity_checker": child},
        llm_client=llm,
        tool_registry=_registry(),
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        subagent_executor=executor,
    ).run(parent, {"request": {"topic": "chips"}})

    assert result.success is True
    assert [event["event_type"] for event in result.events if "subagent" in event["event_type"]] == [
        "subagent_delegation_requested",
        "subagent_failed",
    ]
    assert "agent_policy_blocked" in llm.requests[2].messages[1]["content"]
    assert "nested_agent" in llm.requests[2].messages[1]["content"]


def test_agent_runner_retries_after_allowed_subagent_failure() -> None:
    class FailingSubAgentExecutor:
        def run(self, task: SubAgentTask) -> SubAgentResult:
            return SubAgentResult(
                child_agent_id=task.child_agent_id,
                success=False,
                status="failed",
                error="citation checker unavailable",
            )

    llm = FakeLLMClient(
        [
            (
                '{"action_type":"delegate_to_subagent",'
                '"subagent_id":"citation_sanity_checker",'
                '"subagent_task":"check citations",'
                '"handoff_reason":"citation risk"}'
            ),
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    agent = AgentSpec(
        agent_id="writer",
        name="WriterAgent",
        role="Write",
        goal="Write report",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        loop_policy=AgentLoopPolicy(allow_subagents=True),
        allowed_subagents=["citation_sanity_checker"],
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        subagent_executor=FailingSubAgentExecutor(),
    ).run(agent, {"request": {"topic": "chips"}})

    assert result.success is True
    subagent_failed = [
        event for event in result.events if event["event_type"] == "subagent_failed"
    ]
    assert subagent_failed[0]["error"] == "citation checker unavailable"
    assert "subagent delegation returned non-success status: failed" in (
        llm.requests[1].messages[1]["content"]
    )


def test_agent_runner_waits_for_tool_approval_with_diagnostics() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="publish.record",
            side_effect="publishing",
            requires_approval=True,
        ),
        lambda args: {"published": True},
    )
    llm = FakeLLMClient(
        ['{"action_type":"tool_call","tool_name":"publish.record","tool_args":{"item_id":"r1"}}']
    )
    agent = AgentSpec(
        agent_id="publisher",
        name="Publisher",
        role="Publish",
        goal="Publish item",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="publish_result",
        allowed_tools=["publish.record"],
        tool_policy=ToolPolicy(
            allowed_tools=["publish.record"],
            allow_dangerous_tools=True,
        ),
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"item_id": "r1"}},
    )

    assert result.success is False
    assert result.status == AgentLoopStatus.WAITING_FOR_APPROVAL
    assert result.metrics.tool_approval_requests == 1
    assert result.diagnostics is not None
    assert result.diagnostics.stop_reason == AgentLoopStopReason.TOOL_APPROVAL_REQUIRED
    assert result.diagnostics.issues[0].tool_name == "publish.record"
    assert result.events[-1]["event_type"] == "agent_waiting_for_approval"


def test_agent_runner_persists_waiting_for_approval_iteration_checkpoint(tmp_path) -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(registry, approval_store=approval_store, run_id="run-approval")
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call",'
                '"tool_name":"control.request_human_review",'
                '"tool_args":{'
                '"requested_action":"review:analysis",'
                '"reason":"editor review required",'
                '"risk_level":"high",'
                '"payload":{"draft_id":"draft-1"},'
                '"task_id":"task-review",'
                '"requested_by":"analyst"}}'
            )
        ]
    )
    store = LocalJsonConversationStore(tmp_path)
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["control.request_human_review"],
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=registry,
        conversation_store=store,
    ).run(
        agent,
        {"request": {"item_id": "r1"}},
        conversation_id="conversation-approval",
        run_id="run-approval",
        step_id="publish",
        workflow_checkpoint_id="cp-approval",
    )
    checkpoint = store.read_iteration_checkpoint("conversation-approval")

    assert result.status == AgentLoopStatus.WAITING_FOR_APPROVAL
    approval = approval_store.list_approvals()[0]
    assert checkpoint is not None
    assert checkpoint.status == "waiting_for_approval"
    assert checkpoint.stop_reason == "tool_approval_required"
    assert checkpoint.run_id == "run-approval"
    assert checkpoint.step_id == "publish"
    assert checkpoint.workflow_checkpoint_id == "cp-approval"
    assert checkpoint.last_tool_observation is not None
    assert checkpoint.last_tool_observation["tool_name"] == "control.request_human_review"
    assert checkpoint.last_tool_observation["status"] == "succeeded"
    assert checkpoint.last_tool_observation["approval_id"] == approval.approval_id
    assert checkpoint.metadata["approval_ids"] == [approval.approval_id]


def test_agent_runner_waits_for_human_review_control_approval() -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(registry, approval_store=approval_store, run_id="run-review")
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call",'
                '"tool_name":"control.request_human_review",'
                '"tool_args":{'
                '"requested_action":"review:analysis",'
                '"reason":"editor review required",'
                '"risk_level":"high",'
                '"payload":{"draft_id":"draft-1"},'
                '"task_id":"task-review",'
                '"requested_by":"analyst"}}'
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
        allowed_tools=["control.request_human_review"],
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )
    approval = approval_store.list_approvals()[0]
    waiting_event = result.events[-1]
    issue_metadata = result.diagnostics.issues[0].metadata if result.diagnostics else {}

    assert result.success is False
    assert result.status == AgentLoopStatus.WAITING_FOR_APPROVAL
    assert result.metrics.tool_approval_requests == 1
    assert result.diagnostics is not None
    assert result.diagnostics.summary == "human review requested by control.request_human_review"
    assert issue_metadata["approval_id"] == approval.approval_id
    assert issue_metadata["approval_kind"] == "human_review"
    assert issue_metadata["control_action"] == "request_human_review"
    assert waiting_event["event_type"] == "agent_waiting_for_approval"
    assert waiting_event["approval_id"] == approval.approval_id
    assert waiting_event["approval_kind"] == "human_review"
    assert waiting_event["control_action"] == "request_human_review"
    assert approval.run_id == "run-review"
    assert approval.requested_action == "review:analysis"


def test_agent_runner_waits_for_escalation_control_approval() -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(registry, approval_store=approval_store, run_id="run-escalate")
    llm = FakeLLMClient(
        [
            (
                '{"action_type":"tool_call",'
                '"tool_name":"control.escalate",'
                '"tool_args":{'
                '"escalation_type":"source_outage",'
                '"reason":"official source unavailable",'
                '"severity":"critical",'
                '"payload":{"source_id":"official-ai"},'
                '"task_id":"task-escalate",'
                '"requested_by":"collector"}}'
            )
        ]
    )
    agent = AgentSpec(
        agent_id="collector",
        name="Collector",
        role="Collect",
        goal="Collect sources",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="collection_result",
        allowed_tools=["control.escalate"],
    )

    result = AgentRunner(llm_client=llm, tool_registry=registry).run(
        agent,
        {"request": {"topic": "chips"}},
    )
    approval = approval_store.list_approvals()[0]
    waiting_event = result.events[-1]
    issue_metadata = result.diagnostics.issues[0].metadata if result.diagnostics else {}

    assert result.success is False
    assert result.status == AgentLoopStatus.WAITING_FOR_APPROVAL
    assert result.diagnostics is not None
    assert result.diagnostics.summary == (
        "human escalation requested by control.escalate: source_outage"
    )
    assert issue_metadata["approval_id"] == approval.approval_id
    assert issue_metadata["approval_kind"] == "escalation"
    assert issue_metadata["control_action"] == "escalate"
    assert issue_metadata["escalation_type"] == "source_outage"
    assert waiting_event["approval_id"] == approval.approval_id
    assert waiting_event["approval_kind"] == "escalation"
    assert waiting_event["control_action"] == "escalate"
    assert waiting_event["escalation_type"] == "source_outage"
    assert approval.requested_action == "escalate:source_outage"


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
        run_id="run-1",
        step_id="agent",
        workflow_checkpoint_id="cp-1",
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
    cursor = store.read_cursor("conversation-1")
    checkpoint = store.read_iteration_checkpoint("conversation-1")
    assert cursor is not None
    assert cursor.message_offset == 2
    assert cursor.message_id == messages[2].message_id
    assert cursor.run_id == "run-1"
    assert cursor.step_id == "agent"
    assert cursor.workflow_checkpoint_id == "cp-1"
    assert cursor.metadata == {
        "agent_id": "analyst",
        "iterations": 1,
        "message_type": "agent_result",
        "status": "accepted",
        "stop_reason": "final_output_accepted",
        "success": True,
    }
    assert checkpoint is not None
    assert checkpoint.conversation_id == "conversation-1"
    assert checkpoint.agent_id == "analyst"
    assert checkpoint.run_id == "run-1"
    assert checkpoint.step_id == "agent"
    assert checkpoint.workflow_checkpoint_id == "cp-1"
    assert checkpoint.message_id == messages[2].message_id
    assert checkpoint.status == "accepted"
    assert checkpoint.iteration == 1
    assert checkpoint.stop_reason == "final_output_accepted"
    assert checkpoint.trace_summary["iteration_count"] == 1
    assert checkpoint.diagnostics_summary["summary"] == "agent output accepted"
    assert checkpoint.llm_call_artifact_ids == ["analyst:llm_call:1"]
    assert checkpoint.metadata["success"] is True
    assert checkpoint.metadata["event_count"] == len(result.events)


def test_agent_runner_rejects_resume_cursor_for_different_agent(tmp_path) -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    store = LocalJsonConversationStore(tmp_path)
    store.write_cursor(
        ConversationCursor(
            conversation_id="conversation-resume",
            message_offset=0,
            message_id="message-0",
            metadata={"agent_id": "other-agent"},
        )
    )

    with pytest.raises(ValueError, match="conversation cursor agent_id mismatch"):
        AgentRunner(
            llm_client=llm,
            tool_registry=_registry(),
            conversation_store=store,
        ).run(
            _agent(),
            {"request": {"topic": "chips"}},
            conversation_id="conversation-resume",
            resume_from_cursor=True,
        )


def test_agent_runner_rejects_resume_checkpoint_for_different_agent(tmp_path) -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    store = LocalJsonConversationStore(tmp_path)
    store.write_cursor(
        ConversationCursor(
            conversation_id="conversation-resume",
            message_offset=0,
            message_id="message-0",
            metadata={"agent_id": "analyst"},
        )
    )
    store.write_iteration_checkpoint(
        AgentIterationCheckpoint(
            conversation_id="conversation-resume",
            agent_id="other-agent",
            iteration=1,
            status="accepted",
        )
    )

    with pytest.raises(ValueError, match="agent iteration checkpoint agent_id mismatch"):
        AgentRunner(
            llm_client=llm,
            tool_registry=_registry(),
            conversation_store=store,
        ).run(
            _agent(),
            {"request": {"topic": "chips"}},
            conversation_id="conversation-resume",
            resume_from_cursor=True,
        )


def test_agent_runner_compacts_conversation_when_threshold_is_exceeded(tmp_path) -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"final_output","output":{"wrong_key":{"summary":"missing"}}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    store = LocalJsonConversationStore(tmp_path)
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
        loop_policy=AgentLoopPolicy(
            conversation_compaction_max_messages=3,
            conversation_compaction_keep_last=2,
        ),
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        conversation_store=store,
    ).run(
        agent,
        {"request": {"topic": "chips"}},
        conversation_id="conversation-compact",
    )
    compaction = store.get_compaction("conversation-compact")

    assert result.success is True
    assert compaction is not None
    assert compaction.original_message_count == 5
    assert compaction.compacted_message_count == 3
    assert compaction.retained_message_count == 2
    assert compaction.metadata["retained_message_ids"]
    assert "Compacted 3 older conversation messages" in compaction.summary
    assert store.get_summary("conversation-compact") == compaction.summary
    messages = store.read_messages("conversation-compact")
    assert [message.metadata.get("message_type") for message in messages] == [
        "conversation_compaction",
        "agent_loop_diagnostics",
        "agent_result",
    ]
    assert messages[0].content["summary"] == compaction.summary
    cursor = store.read_cursor("conversation-compact")
    assert cursor is not None
    assert cursor.message_offset == 2
    assert cursor.message_id == messages[-1].message_id
    assert cursor.metadata["message_type"] == "agent_result"


def test_agent_runner_can_include_cursor_context_in_loop_inputs(tmp_path) -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    store = LocalJsonConversationStore(tmp_path)
    store.write_summary("conversation-resume", "prior summary")
    store.write_cursor(
        ConversationCursor(
            conversation_id="conversation-resume",
            message_offset=4,
            message_id="message-4",
            run_id="run-prior",
            step_id="agent-prior",
        )
    )
    store.write_iteration_checkpoint(
        AgentIterationCheckpoint(
            conversation_id="conversation-resume",
            agent_id="analyst",
            iteration=4,
            status="waiting_for_approval",
            stop_reason="tool_approval_required",
            trace_summary={"iteration_count": 4},
            diagnostics_summary={"summary": "tool approval required"},
        )
    )

    inputs = {"request": {"topic": "chips"}}

    AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        conversation_store=store,
    ).run(
        _agent(),
        inputs,
        conversation_id="conversation-resume",
        resume_from_cursor=True,
    )

    prompt = llm.requests[0].messages[1]["content"]
    messages = store.read_messages("conversation-resume")

    assert '"conversation_cursor"' in prompt
    assert '"message_id": "message-4"' in prompt
    assert '"conversation_summary": "prior summary"' in prompt
    assert '"agent_iteration_checkpoint"' in prompt
    assert '"status": "waiting_for_approval"' in prompt
    assert inputs == {"request": {"topic": "chips"}}
    assert messages[0].content == {"request": {"topic": "chips"}}


def test_agent_runner_omits_cursor_context_by_default(tmp_path) -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    store = LocalJsonConversationStore(tmp_path)
    store.write_summary("conversation-resume", "prior summary")
    store.write_cursor(
        ConversationCursor(
            conversation_id="conversation-resume",
            message_offset=4,
            message_id="message-4",
        )
    )
    store.write_iteration_checkpoint(
        AgentIterationCheckpoint(
            conversation_id="conversation-resume",
            agent_id="analyst",
            iteration=4,
            status="waiting_for_approval",
        )
    )

    AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        conversation_store=store,
    ).run(
        _agent(),
        {"request": {"topic": "chips"}},
        conversation_id="conversation-resume",
    )

    prompt = llm.requests[0].messages[1]["content"]

    assert '"conversation_cursor"' not in prompt
    assert '"conversation_summary"' not in prompt
    assert '"agent_iteration_checkpoint"' not in prompt


def test_agent_runner_skips_conversation_compaction_when_disabled(tmp_path) -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"chips"}}',
            '{"action_type":"final_output","output":{"wrong_key":{"summary":"missing"}}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    store = LocalJsonConversationStore(tmp_path)
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
        loop_policy=AgentLoopPolicy(
            conversation_compaction_enabled=False,
            conversation_compaction_max_messages=3,
            conversation_compaction_keep_last=2,
        ),
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=_registry(),
        conversation_store=store,
    ).run(
        agent,
        {"request": {"topic": "chips"}},
        conversation_id="conversation-no-compact",
    )

    assert result.success is True
    assert store.get_compaction("conversation-no-compact") is None
    assert [message.role for message in store.read_messages("conversation-no-compact")] == [
        "user",
        "tool",
        "judge",
        "diagnostic",
        "assistant",
    ]


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

