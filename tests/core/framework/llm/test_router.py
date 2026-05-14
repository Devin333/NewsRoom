from datetime import UTC, datetime, timedelta

import pytest

from core.framework.llm import (
    InMemoryLLMCooldownTracker,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMCooldownPolicy,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMRoutingPolicy,
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


def test_llm_router_complete_for_uses_agent_task_route_first() -> None:
    writer = StaticClient(LLMResponse(content="writer"))
    editor = StaticClient(LLMResponse(content="editor"))
    default = StaticClient(LLMResponse(content="default"))
    router = LLMRouter(
        routes=[
            ModelRoute(route_id="writer", primary_deployment_id="writer-deployment"),
            ModelRoute(route_id="editor", primary_deployment_id="editor-deployment"),
            ModelRoute(route_id="default", primary_deployment_id="default-deployment"),
        ],
        deployments=[
            ModelDeployment("writer-deployment", "test", "writer-model", writer),
            ModelDeployment("editor-deployment", "test", "editor-model", editor),
            ModelDeployment("default-deployment", "test", "default-model", default),
        ],
        routing_policy=LLMRoutingPolicy(
            default_route_id="default",
            agent_routes={"writer-agent": "writer"},
            task_routes={"review": "default"},
            agent_task_routes={("writer-agent", "review"): "editor"},
        ),
    )

    response = router.complete_for(
        LLMRequest(messages=[{"role": "user", "content": "hi"}]),
        agent_id="writer-agent",
        task_type="review",
    )

    assert response.content == "editor"
    assert writer.call_count == 0
    assert editor.call_count == 1
    assert default.call_count == 0


def test_llm_router_complete_for_explicit_route_overrides_policy() -> None:
    writer = StaticClient(LLMResponse(content="writer"))
    editor = StaticClient(LLMResponse(content="editor"))
    router = LLMRouter(
        routes=[
            ModelRoute(route_id="writer", primary_deployment_id="writer-deployment"),
            ModelRoute(route_id="editor", primary_deployment_id="editor-deployment"),
        ],
        deployments=[
            ModelDeployment("writer-deployment", "test", "writer-model", writer),
            ModelDeployment("editor-deployment", "test", "editor-model", editor),
        ],
        routing_policy=LLMRoutingPolicy(agent_routes={"writer-agent": "writer"}),
    )

    response = router.complete_for(
        LLMRequest(messages=[{"role": "user", "content": "hi"}]),
        route_id="editor",
        agent_id="writer-agent",
    )

    assert response.content == "editor"
    assert writer.call_count == 0
    assert editor.call_count == 1


def test_llm_router_complete_for_raises_when_route_not_resolved() -> None:
    router = LLMRouter(routes=[], deployments=[])

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete_for(
            LLMRequest(messages=[{"role": "user", "content": "hi"}]),
            agent_id="unknown",
            task_type="unknown",
        )

    assert exc_info.value.error_type == "route_not_resolved"
    assert exc_info.value.errors[0]["agent_id"] == "unknown"
    assert exc_info.value.errors[0]["task_type"] == "unknown"


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


def test_llm_router_records_global_budget_usage() -> None:
    primary = StaticClient(
        LLMResponse(content="primary", usage=TokenUsage(input_tokens=1_000, output_tokens=500))
    )
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_total_cost_usd=0.01))
    router = LLMRouter(
        routes=[ModelRoute(route_id="writer", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model-a",
                client=primary,
                pricing=ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0),
            )
        ],
        global_budget_tracker=tracker,
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert response.metadata["llm_global_budget_check"]["within_budget"] is True
    assert response.metadata["llm_global_budget_usage"]["llm_calls"] == 1
    assert response.metadata["llm_global_budget_usage"]["estimated_cost_usd"] == 0.007
    assert response.metadata["llm_route_manifest"]["global_budget_usage"]["llm_calls"] == 1


def test_llm_router_raises_before_call_when_global_budget_preflight_fails() -> None:
    primary = StaticClient(LLMResponse(content="primary"))
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=0))
    router = LLMRouter(
        routes=[ModelRoute(route_id="writer", primary_deployment_id="primary")],
        deployments=[ModelDeployment("primary", "test", "model-a", primary)],
        global_budget_tracker=tracker,
    )

    with pytest.raises(LLMRouteError) as exc_info:
        router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 0
    assert exc_info.value.error_type == "global_budget_exceeded"
    assert exc_info.value.manifest["error"]["error_type"] == "global_budget_exceeded"
    assert exc_info.value.manifest["global_budget_check"]["violations"] == ["max_llm_calls"]


def test_llm_router_falls_back_only_after_retryable_provider_error() -> None:
    primary = FailingClient(
        LLMProviderError(
            "temporary outage",
            provider="primary",
            model="model-a",
            deployment_id="primary",
            error_type="server_error",
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
    assert response.metadata["llm_fallback_count"] == 1
    assert response.metadata["llm_route_manifest"]["fallback_used"] is True
    assert response.metadata["llm_route_manifest"]["metrics"]["fallback_count"] == 1
    assert "llm_fallback_selected" in [
        event["event_type"] for event in response.metadata["llm_router_events"]
    ]
    assert "fallback_selected" in [
        event["metadata"]["event_name"] for event in response.metadata["llm_router_events"]
    ]


def test_llm_router_records_fallback_events_and_redacted_route_manifest() -> None:
    now = datetime(2026, 5, 12, tzinfo=UTC)
    events = []
    primary = FailingClient(
        LLMProviderError(
            "temporary outage",
            provider="primary",
            error_type="server_error",
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
        routing_policy=LLMRoutingPolicy(agent_task_routes={("agent-a", "draft"): "writer"}),
        now_fn=lambda: now,
        event_sink=events.append,
    )
    secret = "sk" + "-router-secret-value"

    response = router.complete_for(
        LLMRequest(
            messages=[{"role": "user", "content": f"hi {secret}"}],
            metadata={"api_key": secret},
        ),
        agent_id="agent-a",
        task_type="draft",
    )

    event_payloads = response.metadata["llm_router_events"]
    manifest = response.metadata["llm_route_manifest"]

    assert [event.event_type for event in events] == [
        "llm_route_started",
        "llm_deployment_attempt_started",
        "llm_deployment_attempt_failed",
        "llm_fallback_selected",
        "llm_deployment_attempt_started",
        "llm_deployment_attempt_succeeded",
        "llm_route_completed",
    ]
    assert [event["event_type"] for event in event_payloads] == [event.event_type for event in events]
    assert "route_attempt_failed" in event_payloads[2]["metadata"]["event_aliases"]
    assert "fallback_selected" in event_payloads[3]["metadata"]["event_aliases"]
    assert event_payloads[0]["occurred_at"] == "2026-05-12T00:00:00Z"
    assert manifest["schema_version"] == "newsroom.llm_route_manifest.v1"
    assert manifest["status"] == "succeeded"
    assert manifest["selected_deployment_id"] == "fallback"
    assert manifest["fallback_count"] == 1
    assert manifest["metrics"]["provider_error_count"] == 1
    assert manifest["provider_resolution_trace"][0] == {
        "source": "agent_task_route",
        "matched": True,
        "agent_id": "agent-a",
        "task_type": "draft",
        "route_id": "writer",
    }
    assert manifest["redacted_request"]["metadata"]["api_key"] == "[redacted]"
    assert secret not in str(manifest)
    assert "[redacted]" in str(manifest)


def test_llm_router_rejects_fallback_missing_required_capability() -> None:
    primary = FailingClient(
        LLMProviderError(
            "temporary outage",
            provider="primary",
            error_type="server_error",
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
        "server_error",
        "missing_required_capability",
    ]


def test_llm_router_does_not_fallback_after_non_retryable_provider_error() -> None:
    primary = FailingClient(
        LLMProviderError(
            "bad request",
            provider="primary",
            error_type="invalid_request",
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


def test_llm_router_skips_static_cooldown_primary_and_uses_fallback() -> None:
    now = datetime(2026, 5, 12, tzinfo=UTC)
    primary = StaticClient(LLMResponse(content="primary"))
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
            ModelDeployment(
                "primary",
                "test",
                "model-a",
                primary,
                cooldown_until=now + timedelta(seconds=60),
            ),
            ModelDeployment("fallback", "test", "model-b", fallback),
        ],
        now_fn=lambda: now,
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert primary.call_count == 0
    assert fallback.call_count == 1
    assert response.content == "fallback"
    assert response.metadata["llm_attempted_deployments"] == ["primary", "fallback"]
    assert response.metadata["llm_fallback_used"] is True


def test_llm_router_records_cooldown_skip_with_w04_event_alias() -> None:
    now = datetime(2026, 5, 12, tzinfo=UTC)
    primary = StaticClient(LLMResponse(content="primary"))
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
            ModelDeployment(
                "primary",
                "test",
                "model-a",
                primary,
                cooldown_until=now + timedelta(seconds=60),
            ),
            ModelDeployment("fallback", "test", "model-b", fallback),
        ],
        now_fn=lambda: now,
    )

    response = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    skipped = next(
        event
        for event in response.metadata["llm_router_events"]
        if event["event_type"] == "llm_deployment_skipped"
    )
    assert skipped["metadata"]["event_name"] == "deployment_skipped_cooldown"
    assert "deployment_skipped_cooldown" in skipped["metadata"]["event_aliases"]


def test_llm_router_records_dynamic_cooldown_after_retryable_failure() -> None:
    now = datetime(2026, 5, 12, tzinfo=UTC)
    clock = {"now": now}
    tracker = InMemoryLLMCooldownTracker(
        LLMCooldownPolicy(
            cooldown_on_rate_limit_seconds=120,
            cooldown_on_server_error_seconds=30,
            failure_count_threshold=1,
        ),
        now_fn=lambda: clock["now"],
    )
    primary = FailingClient(
        LLMProviderError(
            "rate limited",
            provider="primary",
            error_type="rate_limit",
            retryable=True,
            status_code=429,
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
        cooldown_tracker=tracker,
        now_fn=lambda: clock["now"],
    )

    first = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))
    second = router.complete("writer", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    state = tracker.state("primary")

    assert first.content == "fallback"
    assert second.content == "fallback"
    assert primary.call_count == 1
    assert fallback.call_count == 2
    assert state is not None
    assert state.consecutive_failures == 1
    assert state.cooldown_until == now + timedelta(seconds=120)
    assert second.metadata["llm_attempted_deployments"] == ["primary", "fallback"]


def test_llm_cooldown_tracker_resets_failures_on_success() -> None:
    now = datetime(2026, 5, 12, tzinfo=UTC)
    tracker = InMemoryLLMCooldownTracker(
        LLMCooldownPolicy(failure_count_threshold=1),
        now_fn=lambda: now,
    )
    tracker.record_failure(
        "primary",
        LLMProviderError(
            "temporary",
            error_type="server_error",
            retryable=True,
            status_code=503,
        ),
    )

    tracker.record_success("primary")

    assert tracker.state("primary") is None


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
    assert "llm_fallback_selected" in [event["event_type"] for event in exc_info.value.events]
    assert exc_info.value.manifest["status"] == "failed"
    assert exc_info.value.manifest["fallback_count"] == 1
    assert exc_info.value.manifest["error"]["error_type"] == "provider_error"


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
