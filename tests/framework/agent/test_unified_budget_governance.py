from __future__ import annotations

import json

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec
from framework.llm import (
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMRequest,
    LLMResponse,
    LLMRouter,
    ModelContextProfile,
    ModelDeployment,
    ModelPricing,
    ModelRoute,
    TokenUsage,
)
from framework.tool import ToolExecutor, ToolRegistry


class _BoundRouterClient:
    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    def manages_global_budget(self) -> bool:
        return self._router.manages_global_budget()

    def complete(self, request: LLMRequest) -> LLMResponse:
        return self._router.complete("writer", request)


def test_router_managed_agent_call_is_settled_once() -> None:
    provider = FakeLLMClient(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "action_type": "final_output",
                        "output": {"output": {"summary": "done"}},
                    }
                ),
                usage=TokenUsage(input_tokens=12, output_tokens=8),
            )
        ]
    )
    profile = ModelContextProfile(
        deployment_id="primary",
        provider="test",
        model="demo",
        physical_context_window_tokens=8192,
        max_output_tokens=1024,
        default_output_tokens=256,
        tokenizer_family="test-byte",
        tokenizer_revision="test-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision="test-profile-v1",
        allow_conservative_fallback=True,
    )
    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=1),
        run_id="run-agent-budget",
    )
    router = LLMRouter(
        routes=[ModelRoute("writer", "primary")],
        deployments=[
            ModelDeployment(
                "primary",
                "test",
                "demo",
                provider,
                pricing=ModelPricing(input_usd_per_1m_tokens=1.0),
                context_profile=profile,
            )
        ],
        global_budget_tracker=tracker,
    )
    agent = AgentSpec(
        agent_id="budget-agent",
        name="Budget Agent",
        instructions="Return a final answer.",
        loop_policy=AgentLoopPolicy(max_iterations=1),
    )

    first = AgentLoop(
        llm_client=_BoundRouterClient(router),
        tool_executor=ToolExecutor(ToolRegistry()),
        global_budget_tracker=tracker,
    ).run(agent, {"topic": "budget"}, [], run_id="run-agent-budget")

    assert first.success is True
    assert provider.call_count == 1
    assert tracker.usage.llm_calls == 1
    assert tracker.canonical_snapshot()["ledger_revision"] == 2

    second = AgentLoop(
        llm_client=_BoundRouterClient(router),
        tool_executor=ToolExecutor(ToolRegistry()),
        global_budget_tracker=tracker,
    ).run(agent, {"topic": "budget"}, [], run_id="run-agent-budget")

    assert second.success is False
    assert second.to_dict()["termination_reason"] == "global_budget_exceeded"
    assert provider.call_count == 1
    assert second.metrics.global_budget_check is not None
    assert second.metrics.global_budget_check["violations"] == ["max_llm_calls"]
