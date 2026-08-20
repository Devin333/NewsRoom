from __future__ import annotations

from collections.abc import Iterator

import pytest

from framework.llm import (
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMRequest,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMStreamEvent,
    ModelContextProfile,
    ModelDeployment,
    ModelRoute,
    TokenUsage,
)
from framework.shared.graph_identity import GraphExecutionIdentity


IDENTITY = GraphExecutionIdentity(
    run_id="run-router-identity",
    graph_id="graph-newsroom",
    graph_version="v2",
    graph_ref="graph-newsroom@v2",
    graph_checksum="sha256:" + "a" * 64,
    node_id="writer",
    node_instance_id="writer-instance",
    activity_id="activity-1",
    attempt=1,
)


class _IdentityClient:
    def __init__(self, response_identity: GraphExecutionIdentity | None, *, return_none: bool = False) -> None:
        self.response_identity = response_identity
        self.return_none = return_none

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self.return_none:
            return None  # type: ignore[return-value]
        return LLMResponse(
            content="ok",
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            execution_identity=self.response_identity,
        )

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        yield LLMStreamEvent(
            event_type="message_start",
            execution_identity=self.response_identity,
        )
        yield LLMStreamEvent(
            event_type="text_delta",
            text_delta="ok",
            execution_identity=self.response_identity,
        )
        yield LLMStreamEvent(
            event_type="usage_delta",
            usage_delta=TokenUsage(output_tokens=1),
            execution_identity=self.response_identity,
        )
        yield LLMStreamEvent(
            event_type="message_complete",
            execution_identity=self.response_identity,
        )


def _router(client: _IdentityClient, **kwargs) -> LLMRouter:
    profile = ModelContextProfile(
        provider="test",
        model="demo",
        deployment_id="primary",
        physical_context_window_tokens=4096,
        max_output_tokens=256,
        default_output_tokens=128,
        tokenizer_family="test-byte",
        tokenizer_revision="test-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision="v1",
        allow_conservative_fallback=True,
    )
    return LLMRouter(
        routes=[ModelRoute("writer", "primary")],
        deployments=[
            ModelDeployment(
                "primary",
                "test",
                "demo",
                client,
                context_profile=profile,
            )
        ],
        **kwargs,
    )


def test_graph_request_rejects_provider_response_without_identity() -> None:
    router = _router(_IdentityClient(None))

    with pytest.raises(LLMRouteError) as raised:
        router.complete("writer", LLMRequest(messages=[], execution_identity=IDENTITY))

    assert raised.value.error_type == "response_identity_mismatch"
    assert raised.value.errors[0]["expected_identity"] == IDENTITY.to_dict()
    assert raised.value.errors[0]["actual_identity"] is None


def test_graph_request_rejects_provider_returning_none() -> None:
    router = _router(_IdentityClient(None, return_none=True))

    with pytest.raises(LLMRouteError) as raised:
        router.complete("writer", LLMRequest(messages=[], execution_identity=IDENTITY))

    assert raised.value.error_type == "response_identity_mismatch"


def test_graph_request_rejects_provider_response_from_another_activity() -> None:
    other = GraphExecutionIdentity(
        run_id=IDENTITY.run_id,
        graph_id=IDENTITY.graph_id,
        graph_version=IDENTITY.graph_version,
        graph_ref=IDENTITY.graph_ref,
        graph_checksum=IDENTITY.graph_checksum,
        node_id=IDENTITY.node_id,
        node_instance_id="other-instance",
        activity_id=IDENTITY.activity_id,
        attempt=IDENTITY.attempt,
    )
    router = _router(_IdentityClient(other))

    with pytest.raises(LLMRouteError) as raised:
        router.complete("writer", LLMRequest(messages=[], execution_identity=IDENTITY))

    assert raised.value.error_type == "response_identity_mismatch"


def test_identity_mismatch_still_settles_observed_provider_usage() -> None:
    other = GraphExecutionIdentity(
        run_id=IDENTITY.run_id,
        graph_id=IDENTITY.graph_id,
        graph_version=IDENTITY.graph_version,
        graph_ref=IDENTITY.graph_ref,
        graph_checksum=IDENTITY.graph_checksum,
        node_id=IDENTITY.node_id,
        node_instance_id="other-instance",
        activity_id=IDENTITY.activity_id,
        attempt=IDENTITY.attempt,
    )
    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=2),
        run_id=IDENTITY.run_id,
    )

    with pytest.raises(LLMRouteError, match="mismatched Graph identity"):
        _router(
            _IdentityClient(other),
            global_budget_tracker=tracker,
        ).complete(
            "writer",
            LLMRequest(messages=[], execution_identity=IDENTITY),
        )

    matching = [
        item
        for item in tracker.canonical_snapshot()["scopes"]
        if item["scope"].get("execution_identity") == IDENTITY.to_dict()
    ]
    assert len(matching) == 1
    assert matching[0]["committed"]["llm_calls"] == 1
    assert matching[0]["committed"]["input_tokens"] == 1
    assert matching[0]["committed"]["output_tokens"] == 1


def test_standalone_request_allows_response_without_graph_identity() -> None:
    response = _router(_IdentityClient(None)).complete(
        "writer",
        LLMRequest(messages=[]),
    )

    assert response.execution_identity is None


def test_graph_stream_preserves_exact_identity_on_every_event() -> None:
    events = list(
        _router(_IdentityClient(IDENTITY)).stream(
            "writer",
            LLMRequest(messages=[], execution_identity=IDENTITY),
        )
    )

    assert all(event.execution_identity == IDENTITY for event in events)
    assert events[-1].event_type == "message_complete"
    assert events[-1].metadata["llm_route_manifest"]["status"] == "succeeded"
    assert (
        events[-1].metadata["llm_route_manifest"]["execution_identity"]
        == IDENTITY.to_dict()
    )


def test_graph_stream_rejects_missing_event_identity() -> None:
    with pytest.raises(LLMRouteError) as raised:
        list(
            _router(_IdentityClient(None)).stream(
                "writer",
                LLMRequest(messages=[], execution_identity=IDENTITY),
            )
        )

    assert raised.value.error_type == "response_identity_mismatch"
    assert raised.value.errors[0]["expected_identity"] == IDENTITY.to_dict()
    assert raised.value.errors[0]["actual_identity"] is None


def test_graph_router_events_carry_exact_execution_identity() -> None:
    recorded = []
    response = _router(
        _IdentityClient(IDENTITY),
        event_sink=recorded.append,
    ).complete(
        "writer",
        LLMRequest(messages=[], execution_identity=IDENTITY),
    )

    assert recorded
    assert all(event.execution_identity == IDENTITY for event in recorded)
    assert all(
        event["execution_identity"] == IDENTITY.to_dict()
        for event in response.metadata["llm_router_events"]
    )
    assert (
        response.metadata["llm_route_manifest"]["execution_identity"]
        == IDENTITY.to_dict()
    )


def test_graph_router_binds_budget_to_request_execution_identity() -> None:
    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=2),
        run_id=IDENTITY.run_id,
    )
    _router(
        _IdentityClient(IDENTITY),
        global_budget_tracker=tracker,
    ).complete(
        "writer",
        LLMRequest(messages=[], execution_identity=IDENTITY),
    )

    matching = [
        item
        for item in tracker.canonical_snapshot()["scopes"]
        if item["scope"].get("execution_identity") == IDENTITY.to_dict()
    ]
    assert len(matching) == 1
    assert matching[0]["committed"]["llm_calls"] == 1


def test_graph_router_rejects_budget_tracker_from_another_run() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=2))

    with pytest.raises(ValueError, match="budget tracker run"):
        _router(
            _IdentityClient(IDENTITY),
            global_budget_tracker=tracker,
        ).complete(
            "writer",
            LLMRequest(messages=[], execution_identity=IDENTITY),
        )


def test_external_budget_operation_id_is_scoped_by_graph_activity() -> None:
    other = GraphExecutionIdentity(
        run_id=IDENTITY.run_id,
        graph_id=IDENTITY.graph_id,
        graph_version=IDENTITY.graph_version,
        graph_ref=IDENTITY.graph_ref,
        graph_checksum=IDENTITY.graph_checksum,
        node_id=IDENTITY.node_id,
        node_instance_id=IDENTITY.node_instance_id,
        activity_id="activity-2",
        attempt=2,
    )
    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=3),
        run_id=IDENTITY.run_id,
    )
    metadata = {"llm_budget_operation_id": "caller-operation-1"}

    _router(
        _IdentityClient(IDENTITY),
        global_budget_tracker=tracker,
    ).complete(
        "writer",
        LLMRequest(
            messages=[],
            metadata=metadata,
            execution_identity=IDENTITY,
        ),
    )
    _router(
        _IdentityClient(other),
        global_budget_tracker=tracker,
    ).complete(
        "writer",
        LLMRequest(
            messages=[],
            metadata=metadata,
            execution_identity=other,
        ),
    )

    graph_scopes = [
        item
        for item in tracker.canonical_snapshot()["scopes"]
        if item["scope"].get("execution_identity") is not None
    ]
    assert len(graph_scopes) == 2
    assert all(item["committed"]["llm_calls"] == 1 for item in graph_scopes)
