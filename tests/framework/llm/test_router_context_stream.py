from __future__ import annotations

from collections.abc import Iterator

import pytest

from framework.llm import (
    CanonicalLLMRequestNormalizer,
    CacheMode,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    InMemoryLLMCache,
    LLMCacheKeyFactory,
    LLMCachePolicy,
    LLMCacheRuntime,
    LLMProviderContextOverflow,
    LLMRequest,
    LLMRequestNormalizerRegistry,
    LLMRequestPreparer,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMRoutingPolicy,
    LLMStreamEvent,
    LLMTokenCount,
    LLMTokenCounterRegistry,
    ModelContextProfile,
    ModelDeployment,
    ModelRoute,
    TokenUsage,
)


class _FixedCounter:
    def __init__(self, total: int) -> None:
        self.total = total

    def count(self, payload, *, profile, normalizer_revision) -> LLMTokenCount:
        return LLMTokenCount(
            message_tokens=self.total,
            tool_tokens=0,
            response_schema_tokens=0,
            media_tokens=0,
            protocol_overhead_tokens=0,
            total_input_tokens=self.total,
            method="exact",
            tokenizer_family=profile.tokenizer_family,
            tokenizer_revision=profile.tokenizer_revision,
            normalizer_revision=normalizer_revision,
        )


class _RecordingBudgetTracker(GlobalBudgetTracker):
    def __init__(self) -> None:
        super().__init__(GlobalBudgetPolicy(max_llm_calls=10))
        self.reservations: list[int | None] = []

    def reserve_prepared_operation(self, **kwargs):  # type: ignore[no-untyped-def]
        self.reservations.append(kwargs["input_tokens"])
        return super().reserve_prepared_operation(**kwargs)


class _ScriptedStreamClient:
    def __init__(
        self,
        *,
        content: str = "streamed",
        usage: TokenUsage | None = None,
        fail_before_visible: bool = False,
        fail_after_visible: bool = False,
    ) -> None:
        self.content = content
        self.usage = usage or TokenUsage(input_tokens=100, output_tokens=4)
        self.fail_before_visible = fail_before_visible
        self.fail_after_visible = fail_after_visible
        self.stream_open_count = 0
        self.complete_count = 0
        self.requests: list[LLMRequest] = []
        self.produced: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.complete_count += 1
        self.requests.append(request)
        return LLMResponse(content=self.content, usage=self.usage)

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        self.stream_open_count += 1
        self.requests.append(request)
        if self.fail_before_visible:
            raise _overflow()
        self.produced.append("message_start")
        yield LLMStreamEvent(event_type="message_start")
        if self.fail_after_visible:
            raise _overflow()
        self.produced.append("text_delta")
        yield LLMStreamEvent(event_type="text_delta", text_delta=self.content)
        self.produced.append("usage_delta")
        yield LLMStreamEvent(event_type="usage_delta", usage_delta=self.usage)
        self.produced.append("message_complete")
        yield LLMStreamEvent(event_type="message_complete", metadata={"finish_reason": "stop"})


def _overflow() -> LLMProviderContextOverflow:
    return LLMProviderContextOverflow(
        "provider overflow",
        provider="test",
        model="model",
        status_code=413,
        provider_error_code="context_length_exceeded",
        provider_reported_limit_tokens=128,
        provider_reported_usage_tokens=129,
    )


def _profile(
    deployment_id: str,
    model: str,
    *,
    physical_limit: int = 512,
) -> ModelContextProfile:
    return ModelContextProfile(
        deployment_id=deployment_id,
        provider="test",
        model=model,
        physical_context_window_tokens=physical_limit,
        max_output_tokens=100,
        default_output_tokens=20,
        tokenizer_family="fixed",
        tokenizer_revision="fixed-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision=f"{deployment_id}-profile-v1",
        operational_input_fraction=1.0,
    )


def _preparer(total: int) -> LLMRequestPreparer:
    normalizers = LLMRequestNormalizerRegistry()
    normalizers.register(
        provider="test",
        revision="canonical-request-v1",
        normalizer=CanonicalLLMRequestNormalizer(),
    )
    counters = LLMTokenCounterRegistry()
    counters.register(
        tokenizer_family="fixed",
        tokenizer_revision="fixed-v1",
        counter=_FixedCounter(total),
    )
    return LLMRequestPreparer(normalizers=normalizers, token_counters=counters)


def _router(
    deployments: list[ModelDeployment],
    *,
    total_tokens: int = 100,
    budget: GlobalBudgetTracker | None = None,
    cache_runtime: LLMCacheRuntime | None = None,
) -> LLMRouter:
    return LLMRouter(
        routes=[
            ModelRoute(
                route_id="route",
                primary_deployment_id=deployments[0].deployment_id,
                fallback_deployment_ids=tuple(
                    deployment.deployment_id for deployment in deployments[1:]
                ),
            )
        ],
        deployments=deployments,
        request_preparer=_preparer(total_tokens),
        global_budget_tracker=budget,
        cache_runtime=cache_runtime,
    )


def _cache_runtime(store: InMemoryLLMCache) -> LLMCacheRuntime:
    return LLMCacheRuntime(
        policy=LLMCachePolicy(
            mode=CacheMode.READ_WRITE,
            cacheable_task_types=("classify",),
            required_dependencies=("prompt_revision",),
        ),
        key_factory=LLMCacheKeyFactory(secret="0123456789abcdef"),
        store=store,
        coordinator=store,
    )


def _cacheable_request() -> LLMRequest:
    return LLMRequest(
        messages=[{"role": "user", "content": "cache this complete stream"}],
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


def test_complete_and_stream_use_identical_preparation() -> None:
    client = _ScriptedStreamClient()
    profile = _profile("primary", "deployment-model")
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "deployment-model",
                client,
                context_profile=profile,
            )
        ]
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "same input"}],
        model="caller-model",
    )

    complete_response = router.complete("route", request)
    stream_events = list(router.stream("route", request))
    terminal = stream_events[-1]

    assert terminal.event_type == "message_complete"
    assert (
        terminal.metadata["llm_prepared_request"]["payload_fingerprint"]
        == complete_response.metadata["llm_prepared_request"]["payload_fingerprint"]
    )
    assert client.requests[0].model == "deployment-model"
    assert client.requests[1].model == "deployment-model"


def test_stream_capacity_rejection_never_opens_provider_iterator() -> None:
    client = _ScriptedStreamClient()
    budget = _RecordingBudgetTracker()
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "small",
                client,
                context_profile=_profile("primary", "small", physical_limit=120),
            )
        ],
        total_tokens=101,
        budget=budget,
    )

    with pytest.raises(LLMRouteError) as raised:
        list(router.stream("route", LLMRequest(messages=[{"role": "user", "content": "x"}])))

    assert raised.value.error_type == "input_limit_exceeded"
    assert client.stream_open_count == 0
    assert budget.reservations == []


def test_stream_remains_incremental_and_settles_admitted_usage() -> None:
    client = _ScriptedStreamClient(usage=TokenUsage(input_tokens=137, output_tokens=4))
    budget = _RecordingBudgetTracker()
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "model",
                client,
                context_profile=_profile("primary", "model"),
            )
        ],
        total_tokens=137,
        budget=budget,
    )
    stream = router.stream("route", LLMRequest(messages=[{"role": "user", "content": "x"}]))

    first = next(stream)
    assert first.event_type == "message_start"
    assert client.produced == ["message_start"]
    remaining = list(stream)

    assert [event.event_type for event in remaining] == [
        "text_delta",
        "usage_delta",
        "message_complete",
    ]
    assert budget.reservations == [137]
    assert budget.usage.llm_calls == 1
    assert budget.usage.token_usage.input_tokens == 137
    assert remaining[-1].metadata["llm_prepared_request"]["token_count"][
        "total_input_tokens"
    ] == 137


def test_overflow_before_visible_event_uses_one_fallback_stream() -> None:
    primary = _ScriptedStreamClient(fail_before_visible=True)
    fallback = _ScriptedStreamClient(content="fallback")
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "primary-model",
                primary,
                context_profile=_profile("primary", "primary-model"),
            ),
            ModelDeployment(
                "fallback",
                "test",
                "fallback-model",
                fallback,
                context_profile=_profile("fallback", "fallback-model"),
            ),
        ]
    )

    events = list(router.stream("route", LLMRequest(messages=[{"role": "user", "content": "x"}])))

    assert primary.stream_open_count == 1
    assert fallback.stream_open_count == 1
    assert [event.text_delta for event in events if event.event_type == "text_delta"] == [
        "fallback"
    ]
    assert events[-1].metadata["llm_deployment_id"] == "fallback"


def test_overflow_after_visible_event_never_splices_fallback() -> None:
    primary = _ScriptedStreamClient(fail_after_visible=True)
    fallback = _ScriptedStreamClient(content="must not appear")
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "primary-model",
                primary,
                context_profile=_profile("primary", "primary-model"),
            ),
            ModelDeployment(
                "fallback",
                "test",
                "fallback-model",
                fallback,
                context_profile=_profile("fallback", "fallback-model"),
            ),
        ]
    )
    stream = router.stream("route", LLMRequest(messages=[{"role": "user", "content": "x"}]))

    assert next(stream).event_type == "message_start"
    with pytest.raises(LLMRouteError) as raised:
        next(stream)

    assert raised.value.error_type == "provider_context_overflow"
    assert primary.stream_open_count == 1
    assert fallback.stream_open_count == 0


def test_completed_stream_is_cached_and_replayed_without_provider_usage() -> None:
    store = InMemoryLLMCache(max_entries=10, default_ttl_seconds=60)
    client = _ScriptedStreamClient(content="cached stream")
    budget = _RecordingBudgetTracker()
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "model",
                client,
                context_profile=_profile("primary", "model"),
            )
        ],
        budget=budget,
        cache_runtime=_cache_runtime(store),
    )
    request = _cacheable_request()

    first = list(router.stream("route", request))
    replay = list(router.stream("route", request))

    assert first[-1].metadata["llm_cache_hit"] is False
    assert replay[-1].metadata["llm_cache_hit"] is True
    assert client.stream_open_count == 1
    assert store.entry_count == 1
    # The replay admits only a logical call; physical token reservation occurs
    # on the provider miss, so the cache hit must not reserve provider tokens.
    assert budget.reservations == [100]
    assert budget.usage.llm_calls == 2
    assert [event.text_delta for event in replay if event.event_type == "text_delta"] == [
        "cached stream"
    ]
    replay_usage = next(event for event in replay if event.event_type == "usage_delta")
    assert replay_usage.usage_delta == TokenUsage()


def test_consumer_close_before_terminal_does_not_cache_partial_stream() -> None:
    store = InMemoryLLMCache(max_entries=10, default_ttl_seconds=60)
    client = _ScriptedStreamClient(content="partial")
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "model",
                client,
                context_profile=_profile("primary", "model"),
            )
        ],
        cache_runtime=_cache_runtime(store),
    )
    stream = router.stream("route", _cacheable_request())

    assert next(stream).event_type == "message_start"
    stream.close()

    assert store.entry_count == 0


def test_stream_for_uses_configured_route_resolution_policy() -> None:
    client = _ScriptedStreamClient(content="resolved")
    router = LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                "primary",
                "test",
                "model",
                client,
                context_profile=_profile("primary", "model"),
            )
        ],
        routing_policy=LLMRoutingPolicy(task_routes={"classify": "route"}),
        request_preparer=_preparer(100),
    )

    events = list(
        router.stream_for(
            LLMRequest(messages=[{"role": "user", "content": "x"}]),
            task_type="classify",
        )
    )

    assert events[-1].metadata["llm_route_id"] == "route"
    assert events[-1].metadata["llm_provider_resolution_trace"][0]["source"] == "task_route"
