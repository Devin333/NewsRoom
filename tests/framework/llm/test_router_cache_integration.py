from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from framework.llm import (
    CacheEntry,
    CacheMode,
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    InMemoryLLMCache,
    InMemoryLLMCooldownTracker,
    LLMCacheKeyFactory,
    LLMCachePolicy,
    LLMCacheRuntime,
    LLMBudgetPolicy,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMCooldownPolicy,
    ModelDeployment,
    ModelContextProfile,
    ModelRoute,
    TokenUsage,
    build_default_request_preparer,
)


UTC = timezone.utc


class CountingCache(InMemoryLLMCache):
    def __init__(self) -> None:
        super().__init__()
        self.get_calls = 0
        self.put_calls = 0

    def get(self, key):  # type: ignore[no-untyped-def]
        self.get_calls += 1
        return super().get(key)

    def put(self, key, entry, *, ttl_seconds):  # type: ignore[no-untyped-def]
        self.put_calls += 1
        return super().put(key, entry, ttl_seconds=ttl_seconds)


class FailingReadWriteCache:
    backend_name = "failing-test-cache"

    def __init__(self) -> None:
        self.get_calls = 0
        self.put_calls = 0

    def get(self, key):  # type: ignore[no-untyped-def]
        self.get_calls += 1
        raise RuntimeError("backend unavailable")

    def put(self, key, entry, *, ttl_seconds):  # type: ignore[no-untyped-def]
        self.put_calls += 1
        raise RuntimeError("backend unavailable")

    def delete(self, key):  # type: ignore[no-untyped-def]
        return False


class RetryableFailureClient:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        raise LLMProviderError(
            "temporary failure",
            provider="test",
            model="primary-model",
            error_type="server_error",
            retryable=True,
            status_code=503,
        )

    def stream(self, request: LLMRequest):  # type: ignore[no-untyped-def]
        raise AssertionError("stream is outside this router complete test")


class SlowCountingClient:
    def __init__(self) -> None:
        self.call_count = 0
        self._lock = threading.Lock()

    def complete(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.call_count += 1
        time.sleep(0.1)
        return LLMResponse(content="single flight response")

    def stream(self, request: LLMRequest):  # type: ignore[no-untyped-def]
        raise AssertionError("stream is outside this router complete test")


def _request() -> LLMRequest:
    return LLMRequest(
        messages=[{"role": "user", "content": "classify this stable input"}],
        temperature=0,
        metadata={
            "task_type": "classify",
            "llm_cache": {
                "scope": {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "policy_scope": "policy-v1",
                },
                "dependencies": {"prompt_revision": "prompt-v1"},
            },
        },
    )


def _runtime(mode: CacheMode, cache) -> LLMCacheRuntime:  # type: ignore[no-untyped-def]
    return LLMCacheRuntime(
        policy=LLMCachePolicy(
            mode=mode,
            cacheable_task_types=("classify",),
            required_dependencies=("prompt_revision",),
        ),
        key_factory=LLMCacheKeyFactory(secret="0123456789abcdef"),
        store=cache,
        coordinator=cache if isinstance(cache, InMemoryLLMCache) else None,
    )


def _seed(
    runtime: LLMCacheRuntime,
    cache: InMemoryLLMCache,
    request: LLMRequest,
    *,
    deployment_id: str = "primary",
    provider: str = "test",
    model: str = "primary-model",
    content: str = "cached response",
) -> None:
    profile = _profile(deployment_id=deployment_id, provider=provider, model=model)
    prepared = build_default_request_preparer([profile]).prepare(request, profile)
    preparation = runtime.prepare(
        request=prepared.normalized_request,
        deployment_id=deployment_id,
        provider=provider,
        model=model,
        prepared_identity=prepared.cache_identity(),
    )
    assert preparation.key is not None
    entry = CacheEntry.from_response(
        key=preparation.key,
        request=prepared.normalized_request,
        response=LLMResponse(
            content=content,
            metadata={
                "finish_reason": "stop",
                "run_id": "old-run-must-not-replay",
                "llm_router_events": [{"event_type": "old"}],
            },
        ),
    )
    assert cache.put(preparation.key, entry, ttl_seconds=60).stored


def _router(
    runtime: LLMCacheRuntime,
    *deployments: ModelDeployment,
    route: ModelRoute | None = None,
    **kwargs,
) -> LLMRouter:
    bound_deployments = tuple(
        deployment
        if deployment.context_profile is not None
        else replace(
            deployment,
            context_profile=_profile(
                deployment_id=deployment.deployment_id,
                provider=deployment.provider,
                model=deployment.model,
            ),
        )
        for deployment in deployments
    )
    return LLMRouter(
        routes=[route or ModelRoute(route_id="route", primary_deployment_id="primary")],
        deployments=bound_deployments,
        cache_runtime=runtime,
        **kwargs,
    )


def _profile(
    *,
    deployment_id: str,
    provider: str,
    model: str,
) -> ModelContextProfile:
    return ModelContextProfile(
        deployment_id=deployment_id,
        provider=provider,
        model=model,
        physical_context_window_tokens=8192,
        max_output_tokens=1024,
        default_output_tokens=256,
        tokenizer_family="test-byte",
        tokenizer_revision="test-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision="test-profile-v1",
        allow_conservative_fallback=True,
    )


def test_cache_hit_precedes_cooldown_and_provider_budget_and_is_current_call_metadata() -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    cache = CountingCache()
    runtime = _runtime(CacheMode.READ_WRITE, cache)
    request = _request()
    _seed(runtime, cache, request)
    client = FakeLLMClient(["provider must not be called"])
    cooldown = InMemoryLLMCooldownTracker(
        LLMCooldownPolicy(failure_count_threshold=1, cooldown_on_server_error_seconds=60),
        now_fn=lambda: now,
    )
    cooldown.record_failure(
        "primary",
        LLMProviderError("down", error_type="server_error", retryable=True, status_code=503),
    )
    budget = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=0))

    response = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", client),
        cooldown_tracker=cooldown,
        global_budget_tracker=budget,
        now_fn=lambda: now,
    ).complete("route", request)

    assert response.content == "cached response"
    assert client.call_count == 0
    assert budget.usage.llm_calls == 0
    assert cooldown.state("primary") is not None
    assert response.metadata["llm_cache_hit"] is True
    assert response.metadata["llm_provider_call"] is False
    assert response.metadata["llm_budget_cost_counted"] is False
    assert response.metadata["llm_budget_request_counted"] is True
    assert response.metadata["llm_route_id"] == "route"
    assert response.metadata["llm_logical_request_count"] == 1
    assert response.metadata["llm_provider_call_count"] == 0
    assert response.metadata["llm_cache_hit_count"] == 1
    assert "run_id" not in response.metadata
    assert response.metadata["llm_router_events"][-1]["event_type"] == "llm_route_completed"
    event_payload = json.dumps(response.metadata["llm_router_events"], sort_keys=True)
    assert "classify this stable input" not in event_payload
    assert "tenant-a" not in event_payload


@pytest.mark.parametrize(
    ("deployment", "route", "error_type"),
    [
        (
            ModelDeployment(
                "primary",
                "test",
                "primary-model",
                FakeLLMClient(["unused"]),
                enabled=False,
            ),
            ModelRoute(route_id="route", primary_deployment_id="primary"),
            "deployment_disabled",
        ),
        (
            ModelDeployment(
                "primary",
                "test",
                "primary-model",
                FakeLLMClient(["unused"]),
            ),
            ModelRoute(
                route_id="route",
                primary_deployment_id="primary",
                required_capabilities=("streaming",),
            ),
            "missing_required_capability",
        ),
    ],
)
def test_disabled_or_capability_incompatible_deployment_cannot_serve_cache(
    deployment: ModelDeployment,
    route: ModelRoute,
    error_type: str,
) -> None:
    cache = CountingCache()
    runtime = _runtime(CacheMode.READ_WRITE, cache)
    request = _request()
    _seed(runtime, cache, request)

    with pytest.raises(LLMRouteError) as raised:
        _router(runtime, deployment, route=route).complete("route", request)

    assert raised.value.error_type == error_type
    assert deployment.client.call_count == 0
    assert cache.get_calls == 0


def test_fallback_entry_is_not_replayed_as_a_recovered_primary_entry() -> None:
    cache = CountingCache()
    runtime = _runtime(CacheMode.READ_WRITE, cache)
    request = _request()
    fallback_client = FakeLLMClient(["fallback response"])
    route = ModelRoute(
        route_id="route",
        primary_deployment_id="primary",
        fallback_deployment_ids=("fallback",),
    )
    first = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", RetryableFailureClient()),
        ModelDeployment("fallback", "test", "fallback-model", fallback_client),
        route=route,
    ).complete("route", request)
    assert first.content == "fallback response"
    assert fallback_client.call_count == 1
    assert first.metadata["llm_provider_call_count"] == 2

    recovered_primary = FakeLLMClient(["new primary response"])
    response = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", recovered_primary),
        ModelDeployment("fallback", "test", "fallback-model", FakeLLMClient(["unused"])),
        route=route,
    ).complete("route", request)

    assert response.content == "new primary response"
    assert response.metadata["llm_deployment_id"] == "primary"
    assert response.metadata["llm_cache_hit"] is False
    assert recovered_primary.call_count == 1


@pytest.mark.parametrize(
    "mode, expected_get_calls, expected_put_calls, expected_provider_calls",
    [
        (CacheMode.DISABLED, 0, 0, 1),
        (CacheMode.OBSERVE, 0, 0, 1),
        (CacheMode.WRITE_ONLY, 0, 1, 1),
        # The owner rechecks after acquiring the single-flight lease.
        (CacheMode.READ_WRITE, 2, 1, 1),
    ],
)
def test_cache_rollout_modes_have_distinct_router_side_effects(
    mode: CacheMode,
    expected_get_calls: int,
    expected_put_calls: int,
    expected_provider_calls: int,
) -> None:
    cache = CountingCache()
    runtime = _runtime(mode, cache)
    request = _request()
    client = FakeLLMClient(["provider response"])
    response = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", client),
    ).complete("route", request)

    assert response.content == "provider response"
    assert client.call_count == expected_provider_calls
    assert cache.get_calls == expected_get_calls
    assert cache.put_calls == expected_put_calls
    assert response.metadata["llm_cache_mode"] == mode.value
    assert response.metadata["llm_cache_hit"] is False
    assert response.metadata["llm_logical_request_count"] == 1
    assert response.metadata["llm_provider_call_count"] == 1
    assert response.metadata["llm_cache_hit_count"] == 0


def test_cache_backend_errors_fail_open_without_hiding_provider_success() -> None:
    cache = FailingReadWriteCache()
    runtime = _runtime(CacheMode.READ_WRITE, cache)
    request = _request()
    client = FakeLLMClient(["provider response"])

    response = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", client),
    ).complete("route", request)

    assert response.content == "provider response"
    assert client.call_count == 1
    assert cache.get_calls == 1
    assert cache.put_calls == 1
    assert response.metadata["llm_cache_hit"] is False
    assert response.metadata["llm_provider_call"] is True
    event_types = {event["event_type"] for event in response.metadata["llm_router_events"]}
    assert "llm_cache_backend_error" in event_types


def test_route_budget_rejection_does_not_populate_cache() -> None:
    cache = CountingCache()
    runtime = _runtime(CacheMode.READ_WRITE, cache)
    response = LLMResponse(content="too expensive", usage=TokenUsage(input_tokens=2))

    with pytest.raises(LLMRouteError) as raised:
        _router(
            runtime,
            ModelDeployment("primary", "test", "primary-model", FakeLLMClient([response])),
            route=ModelRoute(
                route_id="route",
                primary_deployment_id="primary",
                budget_policy=LLMBudgetPolicy(max_tokens_per_call=1),
            ),
        ).complete("route", _request())

    assert raised.value.error_type == "llm_budget_exceeded"
    assert raised.value.manifest["metrics"]["provider_call_count"] == 1
    assert cache.put_calls == 0


def test_observe_mode_never_rejects_a_provider_response_for_cache_validation() -> None:
    cache = CountingCache()
    runtime = _runtime(CacheMode.OBSERVE, cache)
    request = replace(_request(), response_format="json")
    client = FakeLLMClient([LLMResponse(content="not-json")])

    response = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", client),
    ).complete("route", request)

    assert response.content == "not-json"
    assert response.metadata["llm_cache_mode"] == "observe"
    assert cache.get_calls == 0
    assert cache.put_calls == 0


def test_singleflight_collapses_concurrent_router_misses() -> None:
    cache = CountingCache()
    runtime = _runtime(CacheMode.READ_WRITE, cache)
    client = SlowCountingClient()
    router = _router(
        runtime,
        ModelDeployment("primary", "test", "primary-model", client),
    )
    start = threading.Barrier(2)

    def complete_after_barrier() -> LLMResponse:
        start.wait(timeout=1)
        return router.complete("route", _request())

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: complete_after_barrier(), range(2)))

    assert [response.content for response in responses] == [
        "single flight response",
        "single flight response",
    ]
    assert client.call_count == 1
    assert cache.put_calls == 1
    assert sorted(response.metadata["llm_cache_hit"] for response in responses) == [False, True]
