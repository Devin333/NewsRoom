from __future__ import annotations

import json
import inspect

import pytest

from framework.llm import (
    CanonicalLLMRequestNormalizer,
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMProviderContextOverflow,
    LLMRequest,
    LLMRequestNormalizerRegistry,
    LLMRequestPreparer,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMTokenCount,
    LLMTokenCounterRegistry,
    ModelContextProfile,
    ModelDeployment,
    ModelRoute,
    TokenUsage,
)
from framework.llm.routing import router as router_module


class _FixedTokenCounter:
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
        self.reserved_prompt_tokens: list[int | None] = []

    def reserve_prepared_operation(self, **kwargs):  # type: ignore[no-untyped-def]
        self.reserved_prompt_tokens.append(kwargs["input_tokens"])
        return super().reserve_prepared_operation(**kwargs)


class _OverflowClient:
    def __init__(self, model: str) -> None:
        self.model = model
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        raise LLMProviderContextOverflow(
            "bounded context overflow",
            provider="test",
            model=self.model,
            status_code=413,
            provider_error_code="context_length_exceeded",
            provider_reported_limit_tokens=128,
            provider_reported_usage_tokens=129,
        )

    def stream(self, request: LLMRequest):  # type: ignore[no-untyped-def]
        raise AssertionError("stream is not used by complete tests")


def _profile(
    deployment_id: str,
    model: str,
    *,
    physical_limit: int = 512,
    max_output: int = 100,
    default_output: int = 20,
    allow_fallback: bool = False,
) -> ModelContextProfile:
    return ModelContextProfile(
        deployment_id=deployment_id,
        provider="test",
        model=model,
        physical_context_window_tokens=physical_limit,
        max_output_tokens=max_output,
        default_output_tokens=default_output,
        tokenizer_family="fixed",
        tokenizer_revision="fixed-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision=f"{deployment_id}-profile-v1",
        operational_input_fraction=1.0,
        allow_conservative_fallback=allow_fallback,
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
        counter=_FixedTokenCounter(total),
    )
    return LLMRequestPreparer(normalizers=normalizers, token_counters=counters)


def _router(
    deployments: list[ModelDeployment],
    *,
    total_tokens: int = 100,
    budget_tracker: GlobalBudgetTracker | None = None,
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
        global_budget_tracker=budget_tracker,
    )


def test_missing_profile_fails_closed_before_provider_or_budget() -> None:
    client = FakeLLMClient(["unused"])
    budget = _RecordingBudgetTracker()
    router = _router(
        [ModelDeployment("primary", "test", "model-a", client)],
        budget_tracker=budget,
    )

    with pytest.raises(LLMRouteError) as raised:
        router.complete("route", LLMRequest(messages=[{"role": "user", "content": "secret"}]))

    assert raised.value.error_type == "profile_required"
    assert client.call_count == 0
    assert budget.reserved_prompt_tokens == []
    admissions = raised.value.manifest["context_admissions"]
    assert admissions[0]["admission"]["status"] == "profile_required"
    assert admissions[0]["payload_fingerprint"] is None


@pytest.mark.parametrize(
    ("input_request", "expected_status"),
    [
        (LLMRequest(messages=[{"role": "user", "content": "input"}]), "input_limit_exceeded"),
        (
            LLMRequest(messages=[{"role": "user", "content": "input"}], max_tokens=101),
            "output_limit_exceeded",
        ),
    ],
)
def test_input_and_output_rejections_have_no_provider_or_budget_side_effects(
    input_request: LLMRequest,
    expected_status: str,
) -> None:
    client = FakeLLMClient(["unused"])
    budget = _RecordingBudgetTracker()
    profile = _profile("primary", "model-a", physical_limit=120)
    router = _router(
        [ModelDeployment("primary", "test", "model-a", client, context_profile=profile)],
        total_tokens=101,
        budget_tracker=budget,
    )

    with pytest.raises(LLMRouteError) as raised:
        router.complete("route", input_request)

    assert raised.value.error_type == expected_status
    assert client.call_count == 0
    assert budget.reserved_prompt_tokens == []
    assert raised.value.manifest["metrics"]["provider_call_count"] == 0


def test_large_tool_schema_can_overflow_when_message_only_request_fits() -> None:
    profile = _profile(
        "primary",
        "model-a",
        physical_limit=600,
        max_output=100,
        default_output=50,
        allow_fallback=True,
    )
    fit_client = FakeLLMClient(["fit"])
    fit_router = LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                "primary",
                "test",
                "model-a",
                fit_client,
                context_profile=profile,
            )
        ],
    )

    fit_router.complete("route", LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    overflow_client = FakeLLMClient(["unused"])
    overflow_router = LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                "primary",
                "test",
                "model-a",
                overflow_client,
                context_profile=profile,
            )
        ],
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "lookup", "description": "x" * 800, "parameters": {}}],
    )

    with pytest.raises(LLMRouteError) as raised:
        overflow_router.complete("route", request)

    admission = raised.value.manifest["context_admissions"][0]
    assert admission["admission"]["status"] == "input_limit_exceeded"
    assert admission["token_count"]["tool_tokens"] > 0
    assert overflow_client.call_count == 0


def test_capacity_fallback_reprepares_and_dispatches_only_larger_model() -> None:
    primary = FakeLLMClient(["unused"])
    fallback = FakeLLMClient([LLMResponse(content="fallback", usage=TokenUsage(input_tokens=101))])
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "small",
                primary,
                context_profile=_profile("primary", "small", physical_limit=120),
            ),
            ModelDeployment(
                "fallback",
                "test",
                "large",
                fallback,
                context_profile=_profile("fallback", "large", physical_limit=300),
            ),
        ],
        total_tokens=101,
    )

    response = router.complete(
        "route",
        LLMRequest(messages=[{"role": "user", "content": "input"}], model="caller-model"),
    )

    assert response.content == "fallback"
    assert primary.call_count == 0
    assert fallback.call_count == 1
    assert fallback.requests[0].model == "large"
    assert response.metadata["llm_deployment_id"] == "fallback"
    assert response.metadata["llm_prepared_request"]["deployment_id"] == "fallback"
    assert response.metadata["llm_route_manifest"]["context_admissions"][0]["admission"][
        "status"
    ] == "input_limit_exceeded"
    event_types = [event["event_type"] for event in response.metadata["llm_router_events"]]
    assert "llm_context_capacity_fallback_selected" in event_types


def test_all_capacity_rejections_retain_bounded_evidence_for_each_deployment() -> None:
    clients = [FakeLLMClient(["unused"]), FakeLLMClient(["unused"])]
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "small-a",
                clients[0],
                context_profile=_profile("primary", "small-a", physical_limit=120),
            ),
            ModelDeployment(
                "fallback",
                "test",
                "small-b",
                clients[1],
                context_profile=_profile("fallback", "small-b", physical_limit=121),
            ),
        ],
        total_tokens=102,
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "never expose this prompt"}],
        tools=[{"name": "private_tool", "description": "never expose this schema"}],
    )

    with pytest.raises(LLMRouteError) as raised:
        router.complete("route", request)

    assert [client.call_count for client in clients] == [0, 0]
    assert len(raised.value.manifest["context_admissions"]) == 2
    bounded = json.dumps(raised.value.manifest["context_admissions"], sort_keys=True)
    assert "never expose this prompt" not in bounded
    assert "never expose this schema" not in bounded


def test_global_budget_reserves_admitted_component_total() -> None:
    budget = _RecordingBudgetTracker()
    client = FakeLLMClient(
        [LLMResponse(content="ok", usage=TokenUsage(input_tokens=137, output_tokens=3))]
    )
    router = _router(
        [
            ModelDeployment(
                "primary",
                "test",
                "model-a",
                client,
                context_profile=_profile("primary", "model-a"),
            )
        ],
        total_tokens=137,
        budget_tracker=budget,
    )

    response = router.complete("route", LLMRequest(messages=[{"role": "user", "content": "x"}]))

    assert response.content == "ok"
    assert budget.reserved_prompt_tokens == [137]
    assert response.metadata["llm_prepared_request"]["token_count"][
        "total_input_tokens"
    ] == 137


def test_router_admission_does_not_use_legacy_rough_token_estimator() -> None:
    source = inspect.getsource(router_module.LLMRouter)

    assert "estimate_request_tokens" not in source


def test_provider_overflow_uses_one_cross_deployment_recovery() -> None:
    primary = _OverflowClient("primary-model")
    fallback = FakeLLMClient(["recovered"])
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

    response = router.complete("route", LLMRequest(messages=[{"role": "user", "content": "x"}]))

    assert response.content == "recovered"
    assert primary.call_count == 1
    assert fallback.call_count == 1
    overflow_event = next(
        event
        for event in response.metadata["llm_router_events"]
        if event["event_type"] == "llm_provider_context_overflow_observed"
    )
    assert overflow_event["metadata"]["provider_reported_limit_tokens"] == 128
    assert overflow_event["metadata"]["provider_reported_usage_tokens"] == 129
    assert "bounded context overflow" not in json.dumps(overflow_event)


def test_second_provider_overflow_does_not_open_another_fallback() -> None:
    primary = _OverflowClient("primary-model")
    fallback = _OverflowClient("fallback-model")
    third = FakeLLMClient(["must not be called"])
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
            ModelDeployment(
                "third",
                "test",
                "third-model",
                third,
                context_profile=_profile("third", "third-model"),
            ),
        ]
    )

    with pytest.raises(LLMRouteError) as raised:
        router.complete("route", LLMRequest(messages=[{"role": "user", "content": "x"}]))

    assert raised.value.error_type == "provider_context_overflow"
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert third.call_count == 0
