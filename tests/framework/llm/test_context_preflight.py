from __future__ import annotations

from copy import deepcopy

import pytest

from framework.llm.context import (
    CanonicalLLMRequestNormalizer,
    LLMContextAdmissionStatus,
    LLMRequestNormalizerRegistry,
    LLMRequestPreparer,
    LLMTokenCount,
    LLMTokenCounterRegistry,
    ModelContextProfile,
    OpenAICompatibleRequestNormalizer,
    build_default_request_preparer,
    build_openai_chat_payload,
)
from framework.llm.clients.fake import FakeLLMClient
from framework.llm.models import LLMRequest
from framework.llm.routing import ModelDeployment


def _profile(**overrides) -> ModelContextProfile:
    payload = {
        "provider": "test",
        "model": "model-a",
        "deployment_id": "deployment-a",
        "physical_context_window_tokens": 4096,
        "max_output_tokens": 1024,
        "default_output_tokens": 256,
        "tokenizer_family": "test-tokenizer",
        "tokenizer_revision": "v1",
        "normalizer_revision": "canonical-request-v1",
        "profile_revision": "profile-v1",
        "operational_input_fraction": 1.0,
        "safety_margin_tokens": 64,
        "allow_conservative_fallback": True,
        "provider_auto_truncation": False,
    }
    payload.update(overrides)
    return ModelContextProfile(**payload)


def _preparer(*, counter=None, register_counter: bool = False) -> LLMRequestPreparer:
    normalizers = LLMRequestNormalizerRegistry()
    normalizers.register(
        provider="test",
        revision="canonical-request-v1",
        normalizer=CanonicalLLMRequestNormalizer(),
    )
    counters = LLMTokenCounterRegistry()
    if register_counter:
        counters.register(
            tokenizer_family="test-tokenizer",
            tokenizer_revision="v1",
            counter=counter or _FixedTokenCounter(100),
        )
    return LLMRequestPreparer(normalizers=normalizers, token_counters=counters)


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


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"physical_context_window_tokens": 0}, "physical_context_window_tokens"),
        ({"max_output_tokens": 0}, "max_output_tokens"),
        ({"default_output_tokens": 2048}, "default_output_tokens"),
        ({"operational_input_fraction": 0}, "operational_input_fraction"),
        ({"operational_input_fraction": 1.01}, "operational_input_fraction"),
        ({"safety_margin_tokens": -1}, "safety_margin_tokens"),
        ({"profile_revision": ""}, "profile_revision"),
    ],
)
def test_profile_rejects_invalid_values(overrides, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _profile(**overrides)


def test_profile_rejects_deployment_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match deployment"):
        _profile().assert_deployment_identity(
            deployment_id="other",
            provider="test",
            model="model-a",
        )


def test_model_deployment_binds_matching_context_profile() -> None:
    profile = _profile()

    deployment = ModelDeployment(
        deployment_id="deployment-a",
        provider="test",
        model="model-a",
        client=FakeLLMClient(["ok"]),
        context_profile=profile,
    )

    assert deployment.context_profile is profile
    assert deployment.to_dict()["context_profile"]["profile_revision"] == "profile-v1"


def test_model_deployment_rejects_mismatched_context_profile() -> None:
    with pytest.raises(ValueError, match="does not match deployment"):
        ModelDeployment(
            deployment_id="other",
            provider="test",
            model="model-a",
            client=FakeLLMClient(["ok"]),
            context_profile=_profile(),
        )


def test_preparer_uses_explicit_output_and_exact_boundary() -> None:
    profile = _profile(
        physical_context_window_tokens=1000,
        operational_input_fraction=1.0,
        safety_margin_tokens=100,
        max_output_tokens=400,
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=300,
    )
    prepared = _preparer(
        counter=_FixedTokenCounter(600),
        register_counter=True,
    ).prepare(request, profile)

    assert prepared.effective_budget.max_input_tokens == 600
    assert prepared.effective_budget.reserved_output_tokens == 300
    assert prepared.admission.status is LLMContextAdmissionStatus.ADMITTED


def test_preparer_rejects_one_token_over_boundary() -> None:
    profile = _profile(
        physical_context_window_tokens=1000,
        safety_margin_tokens=100,
        max_output_tokens=400,
    )
    request = LLMRequest(messages=[{"role": "user", "content": "hello"}], max_tokens=300)

    prepared = _preparer(
        counter=_FixedTokenCounter(601),
        register_counter=True,
    ).prepare(request, profile)

    assert prepared.effective_budget.max_input_tokens == 600
    assert prepared.admission.status is LLMContextAdmissionStatus.INPUT_LIMIT_EXCEEDED
    assert prepared.admission.provider_call_authorized is False


def test_preparer_uses_profile_default_output() -> None:
    prepared = _preparer(register_counter=True).prepare(
        LLMRequest(messages=[{"role": "user", "content": "hello"}]),
        _profile(default_output_tokens=333),
    )

    assert prepared.effective_budget.requested_output_tokens == 333
    assert prepared.effective_budget.reserved_output_tokens == 333


def test_preparer_rejects_output_limit_without_clamping_request() -> None:
    request = LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=500,
    )
    prepared = _preparer(register_counter=True).prepare(
        request,
        _profile(max_output_tokens=400, default_output_tokens=200),
    )

    assert prepared.admission.status is LLMContextAdmissionStatus.OUTPUT_LIMIT_EXCEEDED
    assert prepared.normalized_request.max_tokens == 500
    assert request.max_tokens == 500


def test_preparer_fails_closed_without_registered_or_permitted_counter() -> None:
    prepared = _preparer().prepare(
        LLMRequest(messages=[{"role": "user", "content": "hello"}]),
        _profile(allow_conservative_fallback=False),
    )

    assert prepared.token_count.method == "unavailable"
    assert prepared.admission.status is LLMContextAdmissionStatus.COUNTER_UNAVAILABLE


def test_conservative_fallback_is_labeled_and_counts_tools_schema_and_media() -> None:
    request = LLMRequest(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "分析"},
                    {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
                ],
            }
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "x" * 100,
                    "parameters": {"type": "object"},
                },
            }
        ],
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    prepared = _preparer().prepare(request, _profile())

    assert prepared.token_count.method == "conservative_fallback"
    assert prepared.token_count.tool_tokens > 0
    assert prepared.token_count.response_schema_tokens > 0
    assert prepared.token_count.media_tokens > 0
    assert prepared.token_count.total_input_tokens == (
        prepared.token_count.message_tokens
        + prepared.token_count.tool_tokens
        + prepared.token_count.response_schema_tokens
        + prepared.token_count.media_tokens
        + prepared.token_count.protocol_overhead_tokens
    )


def test_fingerprint_is_stable_and_excludes_diagnostic_metadata() -> None:
    preparer = _preparer(register_counter=True)
    profile = _profile()
    base = LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.2,
        metadata={"trace_id": "one"},
    )
    metadata_only = LLMRequest.from_dict(
        {
            **base.to_dict(redact=False),
            "metadata": {"trace_id": "two", "context_window_tokens": 1},
        }
    )

    first = preparer.prepare(base, profile)
    second = preparer.prepare(metadata_only, profile)

    assert first.payload_fingerprint == second.payload_fingerprint
    assert first.token_count == second.token_count
    assert first.effective_budget == second.effective_budget


@pytest.mark.parametrize(
    "changed",
    [
        {"temperature": 0.8},
        {"max_tokens": 400},
        {"tools": [{"type": "function", "function": {"name": "lookup"}}]},
        {"output_schema": {"type": "object", "required": ["answer"]}},
    ],
)
def test_fingerprint_changes_for_response_affecting_payload(changed) -> None:
    preparer = _preparer(register_counter=True)
    profile = _profile()
    base_payload = LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.2,
        max_tokens=300,
    ).to_dict(redact=False)
    changed_payload = deepcopy(base_payload)
    changed_payload.update(changed)

    base = preparer.prepare(LLMRequest.from_dict(base_payload), profile)
    updated = preparer.prepare(LLMRequest.from_dict(changed_payload), profile)

    assert base.payload_fingerprint != updated.payload_fingerprint


def test_preflight_does_not_mutate_semantic_request_on_rejection() -> None:
    request = LLMRequest(
        messages=[
            {"role": "system", "content": "keep"},
            {"role": "user", "content": "question"},
        ],
        tools=[{"type": "function", "function": {"name": "lookup"}}],
    )
    before = request.to_dict(redact=False)

    prepared = _preparer(
        counter=_FixedTokenCounter(10_000),
        register_counter=True,
    ).prepare(request, _profile())

    assert prepared.admission.status is LLMContextAdmissionStatus.INPUT_LIMIT_EXCEEDED
    assert request.to_dict(redact=False) == before
    assert prepared.normalized_request.messages == before["messages"]
    assert prepared.normalized_request.tools == before["tools"]


def test_missing_normalizer_fails_closed_with_redacted_projection() -> None:
    prepared = LLMRequestPreparer(
        normalizers=LLMRequestNormalizerRegistry(),
        token_counters=LLMTokenCounterRegistry(),
    ).prepare(
        LLMRequest(
            messages=[{"role": "user", "content": "secret prompt"}],
            tools=[{"type": "function", "function": {"description": "secret tool"}}],
        ),
        _profile(),
    )

    evidence = prepared.to_dict()
    assert prepared.admission.status is LLMContextAdmissionStatus.NORMALIZER_UNAVAILABLE
    assert "secret prompt" not in str(evidence)
    assert "secret tool" not in str(evidence)


def test_openai_normalizer_adapts_tools_and_output_schema_once() -> None:
    request = LLMRequest(
        messages=[{"role": "user", "content": "hello"}],
        model="caller-override",
        temperature=0.2,
        max_tokens=300,
        tools=[
            {
                "name": "memory.recall",
                "description": "Recall memory",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        },
        output_schema_name="answer_contract",
    )

    normalized = OpenAICompatibleRequestNormalizer().normalize(
        request,
        provider="test-provider",
        model="resolved-model",
    )

    assert normalized.payload == build_openai_chat_payload(
        normalized.request,
        model="resolved-model",
    )
    assert normalized.payload["model"] == "resolved-model"
    assert normalized.request.model == "resolved-model"
    assert normalized.payload["tools"][0]["function"]["name"] == "memory_recall"
    assert normalized.payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "answer_contract",
            "schema": request.output_schema,
            "strict": True,
        },
    }
    assert "output_schema" not in normalized.payload


def test_openai_payload_preserves_multilingual_media_message_shape() -> None:
    request = LLMRequest(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "解释这张图"},
                    {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
                ],
            }
        ],
        response_format="json_object",
    )

    payload = build_openai_chat_payload(request, model="model-a")

    assert payload["messages"] == request.messages
    assert payload["messages"] is not request.messages
    assert payload["response_format"] == {"type": "json_object"}


def test_default_preparer_registers_known_normalizer_by_profile_revision() -> None:
    profile = _profile(
        provider="dashscope",
        normalizer_revision="openai-chat-completions-v1",
    )

    prepared = build_default_request_preparer([profile]).prepare(
        LLMRequest(messages=[{"role": "user", "content": "hello"}]),
        profile,
    )

    assert prepared.admission.status is LLMContextAdmissionStatus.ADMITTED
    assert prepared.normalizer_revision == "openai-chat-completions-v1"


def test_default_preparer_does_not_guess_unknown_normalizer_revision() -> None:
    profile = _profile(normalizer_revision="unknown-provider-v9")

    prepared = build_default_request_preparer([profile]).prepare(
        LLMRequest(messages=[{"role": "user", "content": "hello"}]),
        profile,
    )

    assert prepared.admission.status is LLMContextAdmissionStatus.NORMALIZER_UNAVAILABLE


def test_prepared_cache_identity_is_bounded_and_versioned() -> None:
    profile = _profile()
    request = LLMRequest(
        messages=[{"role": "user", "content": "secret prompt"}],
        tools=[{"name": "secret_tool", "description": "secret schema"}],
    )

    prepared = _preparer().prepare(request, profile)

    identity = prepared.cache_identity()
    assert identity["prepared_request_fingerprint"] == prepared.payload_fingerprint
    assert identity["profile_revision"] == "profile-v1"
    assert identity["normalizer_revision"] == "canonical-request-v1"
    assert "secret prompt" not in str(identity)
    assert "secret schema" not in str(identity)
