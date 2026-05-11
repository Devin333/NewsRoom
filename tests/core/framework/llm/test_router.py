import pytest

from core.framework.llm import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMBudgetPolicy,
    ModelCapabilities,
    ModelDeployment,
    ModelPricing,
    ModelRoute,
    TokenUsage,
)


def test_llm_router_uses_primary_deployment() -> None:
    primary = StaticClient(LLMResponse(content="primary", metadata={"provider": "test"}))
    router = LLMRouter(
        routes=[ModelRoute(route_id="writer", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
            )
        ],
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert response.content == "primary"
    assert primary.call_count == 1
    assert response.metadata["provider"] == "test"
    assert response.metadata["llm_route_id"] == "writer"
    assert response.metadata["llm_deployment_id"] == "primary"
    assert response.metadata["llm_fallback_used"] is False
    assert response.metadata["llm_attempted_deployments"] == ["primary"]


def test_llm_router_invokes_primary_when_required_capabilities_match() -> None:
    primary = StaticClient(LLMResponse(content="primary"))
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                required_capabilities=("json_mode",),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
                capabilities=ModelCapabilities(supports_json_mode=True),
            )
        ],
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 1
    assert response.metadata["llm_capabilities"]["supports_json_mode"] is True


def test_llm_router_rejects_primary_missing_required_capability_before_calling() -> None:
    primary = StaticClient(LLMResponse(content="primary"))
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                required_capabilities=("structured_output",),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
            )
        ],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 0
    assert exc_info.value.error_type == "missing_required_capability"
    assert exc_info.value.attempted_deployments == ("primary",)
    assert exc_info.value.errors[0]["missing_capabilities"] == ["structured_output"]


def test_llm_router_adds_cost_budget_metadata_when_policy_is_configured() -> None:
    primary = StaticClient(
        LLMResponse(content="primary", usage=TokenUsage(input_tokens=1_000, output_tokens=500))
    )
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                budget_policy=LLMBudgetPolicy(max_cost_per_call_usd=0.01),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
                pricing=ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0),
            )
        ],
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert response.metadata["llm_estimated_cost_usd"] == 0.007
    assert response.metadata["llm_budget_check"]["within_budget"] is True
    assert response.metadata["llm_budget_check"]["violations"] == []


def test_llm_router_raises_route_error_for_fail_mode_budget_violation() -> None:
    primary = StaticClient(
        LLMResponse(content="primary", usage=TokenUsage(input_tokens=1_000, output_tokens=500))
    )
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                budget_policy=LLMBudgetPolicy(max_cost_per_call_usd=0.001),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
                pricing=ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0),
            )
        ],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 1
    assert exc_info.value.error_type == "llm_budget_exceeded"
    assert exc_info.value.errors[0]["budget_check"]["estimated_cost_usd"] == 0.007
    assert exc_info.value.errors[0]["budget_check"]["violations"] == ["max_cost_per_call_usd"]


def test_llm_router_returns_failed_budget_check_for_non_fail_policy() -> None:
    primary = StaticClient(
        LLMResponse(content="primary", usage=TokenUsage(input_tokens=1_000, output_tokens=500))
    )
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                budget_policy=LLMBudgetPolicy(
                    max_cost_per_call_usd=0.001,
                    on_budget_exceeded="ask_approval",
                ),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
                pricing=ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0),
            )
        ],
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert response.metadata["llm_budget_check"]["within_budget"] is False
    assert response.metadata["llm_budget_check"]["violations"] == ["max_cost_per_call_usd"]


def test_llm_router_falls_back_only_after_retryable_provider_error() -> None:
    primary = FailingClient(
        LLMProviderError(
            "temporary outage",
            provider="primary",
            error_type="provider_server_error",
            retryable=True,
            status_code=503,
        )
    )
    fallback = StaticClient(LLMResponse(content="fallback"))
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                fallback_deployment_ids=("fallback",),
            )
        ],
        deployments=[
            ModelDeployment("primary", "test", "model-a", primary),
            ModelDeployment("fallback", "test", "model-b", fallback),
        ],
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert response.content == "fallback"
    assert response.metadata["llm_deployment_id"] == "fallback"
    assert response.metadata["llm_fallback_used"] is True
    assert response.metadata["llm_attempted_deployments"] == ["primary", "fallback"]


def test_llm_router_rejects_fallback_missing_required_capability() -> None:
    primary = FailingClient(
        LLMProviderError(
            "temporary outage",
            provider="primary",
            error_type="provider_server_error",
            retryable=True,
            status_code=503,
        )
    )
    fallback = StaticClient(LLMResponse(content="fallback"))
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                fallback_deployment_ids=("fallback",),
                required_capabilities=("json_mode",),
            )
        ],
        deployments=[
            ModelDeployment(
                "primary",
                "test",
                "model-a",
                primary,
                capabilities=ModelCapabilities(supports_json_mode=True),
            ),
            ModelDeployment("fallback", "test", "model-b", fallback),
        ],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 1
    assert fallback.call_count == 0
    assert exc_info.value.error_type == "missing_required_capability"
    assert exc_info.value.attempted_deployments == ("primary", "fallback")
    assert [error["error_type"] for error in exc_info.value.errors] == [
        "provider_server_error",
        "missing_required_capability",
    ]


def test_llm_router_does_not_fallback_after_non_retryable_provider_error() -> None:
    primary = FailingClient(
        LLMProviderError(
            "bad request",
            provider="primary",
            error_type="invalid_request_schema",
            retryable=False,
            status_code=400,
        )
    )
    fallback = StaticClient(LLMResponse(content="fallback"))
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                fallback_deployment_ids=("fallback",),
            )
        ],
        deployments=[
            ModelDeployment("primary", "test", "model-a", primary),
            ModelDeployment("fallback", "test", "model-b", fallback),
        ],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 1
    assert fallback.call_count == 0
    assert exc_info.value.error_type == "provider_error"
    assert exc_info.value.retryable is False
    assert exc_info.value.attempted_deployments == ("primary",)


def test_llm_router_raises_when_fallback_chain_exhausted() -> None:
    primary = FailingClient(
        LLMProviderError("primary failed", retryable=True, status_code=503)
    )
    fallback = FailingClient(
        LLMProviderError("fallback failed", retryable=True, status_code=503)
    )
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="writer",
                primary_deployment_id="primary",
                fallback_deployment_ids=("fallback",),
            )
        ],
        deployments=[
            ModelDeployment("primary", "test", "model-a", primary),
            ModelDeployment("fallback", "test", "model-b", fallback),
        ],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert exc_info.value.retryable is True
    assert exc_info.value.attempted_deployments == ("primary", "fallback")
    assert [error["deployment_id"] for error in exc_info.value.errors] == ["primary", "fallback"]


def test_llm_router_raises_for_disabled_deployment() -> None:
    router = LLMRouter(
        routes=[ModelRoute(route_id="writer", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=StaticClient(LLMResponse(content="unused")),
                enabled=False,
            )
        ],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert exc_info.value.error_type == "deployment_disabled"
    assert exc_info.value.attempted_deployments == ("primary",)


def test_llm_route_error_to_dict_redacts_nested_provider_errors() -> None:
    secret = "sk" + "-router-secret-value"
    primary = FailingClient(
        LLMProviderError(
            f"primary failed with {secret}",
            retryable=True,
            status_code=503,
        )
    )
    router = LLMRouter(
        routes=[ModelRoute(route_id="writer", primary_deployment_id="primary")],
        deployments=[ModelDeployment("primary", "test", "model-a", primary)],
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    payload = exc_info.value.to_dict()

    assert secret not in str(payload)
    assert "[redacted]" in str(payload)


class StaticClient:
    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return self._response


class FailingClient:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        raise self._error
