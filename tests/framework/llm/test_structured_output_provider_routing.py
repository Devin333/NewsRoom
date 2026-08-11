from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from framework.llm import (
    CanonicalLLMRequestNormalizer,
    FakeLLMClient,
    LLMProviderError,
    LLMRequest,
    LLMRequestNormalizerRegistry,
    LLMRequestPreparer,
    LLMResponse,
    LLMRouter,
    LLMStructuredOutputProjectionError,
    LLMTokenCount,
    LLMTokenCounterRegistry,
    LOCAL_STRUCTURED_OUTPUT_DIALECT,
    ModelContextProfile,
    ModelDeployment,
    ModelRoute,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
    ProviderStructuredOutputCapability,
    ProviderStructuredOutputPolicy,
    TokenUsage,
    compile_structured_output_contract,
    project_structured_output_contract,
    structured_output_enforcement_keywords,
)
from framework.llm.cache.stream import iter_cached_response_events
from tests.framework.llm._structured_output_release import (
    approved_structured_output_release,
)


_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


def _native_capability(
    deployment: str,
    *,
    schema: Any = _SCHEMA,
    mode: str = "native_strict",
    stream: bool = True,
    keywords: frozenset[str] | None = None,
    supports_local_refs: bool = True,
    max_schema_bytes: int | None = None,
    max_schema_depth: int | None = None,
) -> ProviderStructuredOutputCapability:
    contract = compile_structured_output_contract(schema)
    revision = f"{deployment}-{mode}-v1"
    return ProviderStructuredOutputCapability(
        provider="test-provider",
        deployment=deployment,
        mode=mode,  # type: ignore[arg-type]
        supported_dialect=LOCAL_STRUCTURED_OUTPUT_DIALECT,
        supported_keywords=(
            keywords
            if keywords is not None
            else structured_output_enforcement_keywords(
                contract.canonical_schema
            )
        ),
        supports_local_refs=supports_local_refs,
        max_schema_bytes=max_schema_bytes,
        max_schema_depth=max_schema_depth,
        supports_stream_terminal_validation=stream,
        revision=revision,
        release=approved_structured_output_release(
            provider="test-provider",
            deployment=deployment,
            capability_revision=revision,
        ),
    )


def _json_object_capability(
    deployment: str,
    *,
    stream: bool = True,
) -> ProviderStructuredOutputCapability:
    return ProviderStructuredOutputCapability(
        provider="test-provider",
        deployment=deployment,
        mode="json_object",
        supports_stream_terminal_validation=stream,
        revision=f"{deployment}-json-object-v1",
    )


def _client_config() -> OpenAICompatibleConfig:
    return OpenAICompatibleConfig(
        provider="test-provider",
        base_url="https://llm.example/v1",
        model="test-model",
        api_key_env="TEST_PROVIDER_ROUTING_KEY",
    )


def _response_body(content: str) -> bytes:
    return json.dumps(
        {
            "id": "response-1",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        }
    ).encode("utf-8")


def test_native_projection_is_stable_and_does_not_mutate_contract() -> None:
    source = deepcopy(_SCHEMA)
    contract = compile_structured_output_contract(source)
    capability = _native_capability("native")

    first = project_structured_output_contract(contract, capability)
    second = project_structured_output_contract(contract, capability)
    source["required"].append("later")

    assert first.mode == "native_strict"
    assert first.projection_digest == second.projection_digest
    assert first.enforced_keywords == structured_output_enforcement_keywords(
        contract.canonical_schema
    )
    assert first.omitted_keywords == frozenset()
    assert contract.canonical_schema["required"] == ["answer"]


def test_local_gate_projection_exposes_every_provider_omission() -> None:
    contract = compile_structured_output_contract(_SCHEMA)
    projection = project_structured_output_contract(
        contract,
        _json_object_capability("local"),
        policy=ProviderStructuredOutputPolicy(
            allow_json_object_local_gate=True
        ),
    )

    assert projection.mode == "json_object_local_gate"
    assert projection.provider_schema is None
    assert projection.enforced_keywords == frozenset()
    assert projection.omitted_keywords == structured_output_enforcement_keywords(
        contract.canonical_schema
    )


def test_ineligible_projection_reports_bounded_diagnostics() -> None:
    contract = compile_structured_output_contract(_SCHEMA)
    capability = _native_capability(
        "partial",
        keywords=frozenset({"properties", "required", "type"}),
    )

    with pytest.raises(LLMStructuredOutputProjectionError) as raised:
        project_structured_output_contract(contract, capability)

    assert raised.value.code == "provider_schema_ineligible"
    assert raised.value.diagnostics[0].validator == "provider_keywords_unsupported"
    assert all(
        diagnostic.contract_digest == contract.schema_digest
        for diagnostic in raised.value.diagnostics
    )


_LOCAL_REF_SCHEMA = {
    "$defs": {"answer": {"type": "string", "minLength": 1}},
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"$ref": "#/$defs/answer"}},
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    ("capability", "streaming", "expected_reason"),
    [
        (
            _native_capability(
                "no-refs",
                schema=_LOCAL_REF_SCHEMA,
                supports_local_refs=False,
            ),
            False,
            "provider_local_refs_unsupported",
        ),
        (
            _native_capability("too-small", max_schema_bytes=1),
            False,
            "provider_schema_bytes_exceeded",
        ),
        (
            _native_capability("too-shallow", max_schema_depth=1),
            False,
            "provider_schema_depth_exceeded",
        ),
        (
            _native_capability("no-stream-terminal", stream=False),
            True,
            "provider_stream_terminal_validation_unsupported",
        ),
    ],
)
def test_native_projection_rejects_uncovered_provider_limits(
    capability: ProviderStructuredOutputCapability,
    streaming: bool,
    expected_reason: str,
) -> None:
    schema = _LOCAL_REF_SCHEMA if capability.deployment == "no-refs" else _SCHEMA
    contract = compile_structured_output_contract(schema)

    with pytest.raises(LLMStructuredOutputProjectionError) as raised:
        project_structured_output_contract(
            contract,
            capability,
            streaming=streaming,
        )

    assert expected_reason in {
        diagnostic.validator for diagnostic in raised.value.diagnostics
    }


@pytest.mark.parametrize(
    "capability",
    [None, _native_capability("constrained", mode="constrained")],
)
def test_direct_client_rejects_unconfigured_or_unmapped_capability_before_transport(
    capability: ProviderStructuredOutputCapability | None,
) -> None:
    calls = 0

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return _response_body('{"answer":"ok"}')

    client = OpenAICompatibleClient(
        _client_config(),
        transport=transport,
        structured_output_capability=capability,
    )

    with pytest.raises(LLMProviderError) as raised:
        client.complete(LLMRequest(messages=[], output_schema=_SCHEMA))

    assert raised.value.error_type == "provider_schema_ineligible"
    assert raised.value.retryable is False
    assert raised.value.diagnostics[0]["code"] == "provider_schema_ineligible"
    assert calls == 0


def test_complete_and_stream_share_terminal_contract_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PROVIDER_ROUTING_KEY", "test-key")
    capability = _native_capability("direct")

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        return _response_body('{"answer":"ok"}')

    def stream_transport(request, timeout):  # type: ignore[no-untyped-def]
        chunks = [
            {"choices": [{"delta": {"content": '{"answer":'}}]},
            {
                "choices": [
                    {
                        "delta": {"content": '"ok"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n".encode("utf-8")
        yield b"data: [DONE]\n"

    client = OpenAICompatibleClient(
        _client_config(),
        transport=transport,
        stream_transport=stream_transport,
        structured_output_capability=capability,
    )
    request = LLMRequest(messages=[], output_schema=_SCHEMA)

    complete = client.complete(request)
    events = list(client.stream(request))
    terminal = events[-1]
    complete_validation = complete.metadata["structured_output_validation"]
    stream_validation = terminal.metadata["structured_output_validation"]

    assert complete.structured_output == terminal.structured_output == {
        "answer": "ok"
    }
    assert stream_validation["schema_digest"] == complete_validation[
        "schema_digest"
    ]
    assert stream_validation["projection_digest"] == complete_validation[
        "projection_digest"
    ]
    assert terminal.metadata["provisional"] is False
    assert all(
        event.metadata.get("provisional") is True
        for event in events[:-1]
    )


def test_json_object_projection_keeps_full_local_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PROVIDER_ROUTING_KEY", "test-key")
    payloads: list[dict[str, Any]] = []

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _response_body('{"answer":"","extra":true}')

    client = OpenAICompatibleClient(
        _client_config(),
        transport=transport,
        structured_output_capability=_json_object_capability("direct-local"),
    )
    request = LLMRequest(
        messages=[],
        output_schema=_SCHEMA,
        structured_output_policy=ProviderStructuredOutputPolicy(
            allow_json_object_local_gate=True
        ),
    )

    with pytest.raises(LLMProviderError) as raised:
        client.complete(request)

    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert raised.value.error_type == "structured_output_validation_error"
    assert raised.value.retryable is False


def test_invalid_stream_never_emits_verified_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PROVIDER_ROUTING_KEY", "test-key")

    def stream_transport(request, timeout):  # type: ignore[no-untyped-def]
        chunk = {
            "choices": [
                {
                    "delta": {"content": '{"answer":NaN}'},
                    "finish_reason": "stop",
                }
            ]
        }
        yield f"data: {json.dumps(chunk)}\n".encode("utf-8")
        yield b"data: [DONE]\n"

    client = OpenAICompatibleClient(
        _client_config(),
        stream_transport=stream_transport,
        structured_output_capability=_native_capability("direct"),
    )
    iterator = iter(client.stream(LLMRequest(messages=[], output_schema=_SCHEMA)))

    assert next(iterator).event_type == "message_start"
    provisional = next(iterator)
    assert provisional.event_type == "text_delta"
    assert provisional.metadata["provisional"] is True
    with pytest.raises(LLMProviderError) as raised:
        next(iterator)

    assert raised.value.error_type == "structured_output_parse_error"
    assert raised.value.retryable is False


def test_interrupted_stream_never_emits_verified_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PROVIDER_ROUTING_KEY", "test-key")

    def stream_transport(request, timeout):  # type: ignore[no-untyped-def]
        chunk = {"choices": [{"delta": {"content": '{"answer":"partial'}}]}
        yield f"data: {json.dumps(chunk)}\n".encode("utf-8")

    client = OpenAICompatibleClient(
        _client_config(),
        stream_transport=stream_transport,
        structured_output_capability=_native_capability("direct"),
    )
    iterator = iter(client.stream(LLMRequest(messages=[], output_schema=_SCHEMA)))

    assert next(iterator).event_type == "message_start"
    assert next(iterator).event_type == "text_delta"
    with pytest.raises(LLMProviderError) as raised:
        next(iterator)

    assert raised.value.error_type == "provider_stream_incomplete"
    assert raised.value.retryable is False


def test_cached_stream_replay_exposes_structured_output_only_at_terminal() -> None:
    events = list(
        iter_cached_response_events(
            LLMResponse(
                content='{"answer":"cached"}',
                structured_output={"answer": "cached"},
                usage=TokenUsage(input_tokens=2, output_tokens=2),
                metadata={"structured_output_validation": {"validated": True}},
            ),
            chunk_size=4,
        )
    )

    assert all(event.structured_output is None for event in events[:-1])
    assert events[-1].event_type == "message_complete"
    assert events[-1].structured_output == {"answer": "cached"}
    assert events[-1].metadata["structured_output_validation"]["validated"] is True


class _RecordingTokenCounter:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def count(self, payload, *, profile, normalizer_revision):  # type: ignore[no-untyped-def]
        self.payloads.append(deepcopy(payload))
        return LLMTokenCount(
            message_tokens=1,
            tool_tokens=0,
            response_schema_tokens=1,
            media_tokens=0,
            protocol_overhead_tokens=0,
            total_input_tokens=2,
            method="exact",
            tokenizer_family=profile.tokenizer_family,
            tokenizer_revision=profile.tokenizer_revision,
            normalizer_revision=normalizer_revision,
        )


class _ProjectionRejectingClient(FakeLLMClient):
    @staticmethod
    def supports_structured_output_projection(projection):  # type: ignore[no-untyped-def]
        return False


def _profile(deployment: str, model: str) -> ModelContextProfile:
    return ModelContextProfile(
        deployment_id=deployment,
        provider="test-provider",
        model=model,
        physical_context_window_tokens=1_000,
        max_output_tokens=100,
        default_output_tokens=20,
        tokenizer_family="recording",
        tokenizer_revision="recording-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision=f"{deployment}-profile-v1",
        operational_input_fraction=1.0,
    )


def _preparer(counter: _RecordingTokenCounter) -> LLMRequestPreparer:
    normalizers = LLMRequestNormalizerRegistry()
    normalizers.register(
        provider="test-provider",
        revision="canonical-request-v1",
        normalizer=CanonicalLLMRequestNormalizer(),
    )
    counters = LLMTokenCounterRegistry()
    counters.register(
        tokenizer_family="recording",
        tokenizer_revision="recording-v1",
        counter=counter,
    )
    return LLMRequestPreparer(
        normalizers=normalizers,
        token_counters=counters,
    )


def test_router_reprojects_fallback_before_context_preflight() -> None:
    primary = _ProjectionRejectingClient(["must-not-be-called"])
    fallback = FakeLLMClient(
        [
            LLMResponse(
                content='{"answer":"ok"}',
                structured_output={"answer": "ok"},
                usage=TokenUsage(input_tokens=2, output_tokens=2),
            )
        ]
    )
    counter = _RecordingTokenCounter()
    router = LLMRouter(
        routes=[
            ModelRoute(
                route_id="route",
                primary_deployment_id="primary",
                fallback_deployment_ids=("fallback",),
            )
        ],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test-provider",
                model="model-primary",
                client=primary,
                structured_output_capability=_native_capability(
                    "primary",
                    mode="constrained",
                ),
                context_profile=_profile("primary", "model-primary"),
            ),
            ModelDeployment(
                deployment_id="fallback",
                provider="test-provider",
                model="model-fallback",
                client=fallback,
                structured_output_capability=_json_object_capability("fallback"),
                context_profile=_profile("fallback", "model-fallback"),
            ),
        ],
        request_preparer=_preparer(counter),
    )

    response = router.complete(
        "route",
        LLMRequest(
            messages=[{"role": "user", "content": "answer"}],
            output_schema=_SCHEMA,
            structured_output_policy=ProviderStructuredOutputPolicy(
                allow_json_object_local_gate=True
            ),
        ),
    )

    assert primary.call_count == 0
    assert fallback.call_count == 1
    projection = fallback.requests[0].provider_schema_projection()
    assert projection is not None
    assert projection.deployment == "fallback"
    assert projection.mode == "json_object_local_gate"
    assert counter.payloads[0]["response_format"] == {"type": "json_object"}
    event_types = [
        event["event_type"] for event in response.metadata["llm_router_events"]
    ]
    assert "structured_output_provider_projection_rejected" in event_types
    assert "structured_output_provider_projection_selected" in event_types


def test_router_preserves_only_verified_stream_terminal_object() -> None:
    client = FakeLLMClient(
        [
            LLMResponse(
                content='{"answer":"ok"}',
                structured_output={"answer": "ok"},
                usage=TokenUsage(input_tokens=2, output_tokens=2),
            )
        ]
    )
    counter = _RecordingTokenCounter()
    router = LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="stream")],
        deployments=[
            ModelDeployment(
                deployment_id="stream",
                provider="test-provider",
                model="stream-model",
                client=client,
                structured_output_capability=_native_capability("stream"),
                context_profile=_profile("stream", "stream-model"),
            )
        ],
        request_preparer=_preparer(counter),
    )

    events = list(
        router.stream(
            "route",
            LLMRequest(messages=[], output_schema=_SCHEMA),
        )
    )

    assert all(event.structured_output is None for event in events[:-1])
    assert all(
        event.metadata.get("provisional") is True
        for event in events[:-1]
    )
    assert events[-1].event_type == "message_complete"
    assert events[-1].structured_output == {"answer": "ok"}
    assert events[-1].metadata["provisional"] is False
