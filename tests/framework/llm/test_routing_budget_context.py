from __future__ import annotations

from framework.llm import (
    ContextPolicy,
    CostEstimator,
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMContextGuard,
    LLMFallbackPolicy,
    LLMRequest,
    LLMResponse,
    LLMRouter,
    LLMBudgetPolicy,
    ModelDeployment,
    ModelPricing,
    ModelRoute,
    TokenUsage,
    estimate_request_tokens,
)


def test_router_completes_with_metadata_and_budget() -> None:
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                budget_policy=LLMBudgetPolicy(max_tokens_per_call=10),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="demo",
                client=FakeLLMClient([LLMResponse(content="ok", usage=TokenUsage(input_tokens=2))]),
                pricing=ModelPricing(input_usd_per_1m_tokens=1.0),
            )
        ],
        global_budget_tracker=GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=2)),
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert response.content == "ok"
    assert response.metadata["llm_route_id"] == "writer"
    assert response.metadata["llm_deployment_id"] == "primary"


def test_fallback_policy_selects_next_available_deployment() -> None:
    failed = ModelDeployment("a", "test", "a", FakeLLMClient(["a"]), enabled=False)
    candidate = ModelDeployment("b", "test", "b", FakeLLMClient(["b"]))

    assert LLMFallbackPolicy().next_deployment(failed, [failed, candidate]) == candidate


def test_context_guard_and_cost_estimator_prd_methods() -> None:
    request = LLMRequest(messages=[{"role": "user", "content": "hello"}])
    guard = LLMContextGuard(ContextPolicy(max_context_tokens=100))
    cost = CostEstimator().estimate(
        request,
        LLMResponse(usage=TokenUsage(input_tokens=10, output_tokens=5)),
        ModelPricing(input_usd_per_1m_tokens=1.0, output_usd_per_1m_tokens=2.0),
    )

    assert estimate_request_tokens(request) > 0
    assert guard.check(request).within_context is True
    assert cost == 0.00002
