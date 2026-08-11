from __future__ import annotations

import pytest

from framework.llm.cache import (
    CacheEntry,
    CacheMode,
    CacheResponseValidationError,
    LLMCacheKeyFactory,
    LLMCachePolicy,
)
from framework.llm.models import LLMRequest, LLMResponse


def _request(*, tenant: str = "tenant-a", **metadata) -> LLMRequest:
    cache_metadata = {
        "scope": {
            "tenant_id": tenant,
            "project_id": "project-a",
            "policy_scope": "policy-v1",
        },
        "dependencies": {"prompt_revision": "prompt-v1"},
    }
    cache_metadata.update(metadata.pop("llm_cache", {}))
    return LLMRequest(
        messages=[{"role": "user", "content": "private prompt"}],
        temperature=0,
        metadata={
            "task_type": "classify",
            "run_id": "run-secret",
            "llm_cache": cache_metadata,
            **metadata,
        },
    )


def _policy() -> LLMCachePolicy:
    return LLMCachePolicy(
        mode=CacheMode.READ_WRITE,
        cacheable_task_types=("classify",),
        required_dependencies=("prompt_revision",),
    )


def test_policy_and_key_are_scope_bound_and_redacted() -> None:
    request = _request()
    decision = _policy().evaluate(request)
    assert decision.eligible is True
    assert decision.context is not None

    factory = LLMCacheKeyFactory(secret="0123456789abcdef")
    key = factory.build(
        request=request,
        context=decision.context,
        deployment_id="primary-v1",
        provider="test",
        model="model-v1",
    )
    assert "private prompt" not in key.to_string()
    assert "tenant-a" not in key.to_string()
    assert key.to_string().startswith("newsroom:llm-cache:v2:")

    other = _request(tenant="tenant-b")
    other_decision = _policy().evaluate(other)
    other_key = factory.build(
        request=other,
        context=other_decision.context,
        deployment_id="primary-v1",
        provider="test",
        model="model-v1",
    )
    assert key != other_key


def test_prepared_identity_revision_changes_cache_key() -> None:
    request = _request()
    decision = _policy().evaluate(request)
    assert decision.context is not None
    factory = LLMCacheKeyFactory(secret="0123456789abcdef")
    shared = {
        "request": request,
        "context": decision.context,
        "deployment_id": "primary-v1",
        "provider": "test",
        "model": "model-v1",
    }

    first = factory.build(
        **shared,
        prepared_identity={
            "prepared_request_fingerprint": "sha256:" + "a" * 64,
            "profile_revision": "profile-v1",
            "normalizer_revision": "normalizer-v1",
        },
    )
    revised = factory.build(
        **shared,
        prepared_identity={
            "prepared_request_fingerprint": "sha256:" + "b" * 64,
            "profile_revision": "profile-v2",
            "normalizer_revision": "normalizer-v1",
        },
    )

    assert first.request_digest != revised.request_digest
    assert "profile-v1" not in first.to_string()


def test_policy_returns_stable_bypass_reasons() -> None:
    assert _policy().evaluate(_request(llm_cache={"scope": {}})).reason == "missing_cache_scope"
    assert _policy().evaluate(
        LLMRequest(
            messages=[{"role": "user", "content": "x"}],
            temperature=0.2,
            metadata={
                "task_type": "classify",
                "llm_cache": {
                    "scope": {
                        "tenant_id": "t",
                        "project_id": "p",
                        "policy_scope": "v",
                    },
                    "dependencies": {"prompt_revision": "v1"},
                },
            },
        )
    ).reason == "nondeterministic_temperature"


def test_entry_projection_strips_request_and_route_metadata() -> None:
    request = _request()
    decision = _policy().evaluate(request)
    hmac_secret = "0123456789abcdef"
    key = LLMCacheKeyFactory(secret=hmac_secret).build(
        request=request,
        context=decision.context,
        deployment_id="primary-v1",
        provider="test",
        model="model-v1",
    )
    entry = CacheEntry.from_response(
        key=key,
        request=request,
        response=LLMResponse(
            content="answer",
            raw={
                "provider_response": "raw-provider-response",
                "tool_arguments": {"credential": "tool-argument-secret"},
                "authorization": "provider-authorization-secret",
            },
            metadata={
                "run_id": "run-secret",
                "llm_router_events": [{"prompt": "private prompt"}],
                "finish_reason": "stop",
            },
        ),
    )
    encoded = entry.to_json_bytes().decode("utf-8")
    for forbidden in (
        "private prompt",
        "raw-provider-response",
        "tool-argument-secret",
        "tenant-a",
        "project-a",
        "policy-v1",
        hmac_secret,
        key.to_string(),
        "provider-authorization-secret",
        "run-secret",
    ):
        assert forbidden not in encoded
    assert entry.to_response().content == "answer"


def test_entry_revalidates_structured_output_and_rejects_tools() -> None:
    request = _request()
    request = LLMRequest(
        messages=request.messages,
        temperature=0,
        output_schema={"type": "object", "required": ["label"]},
        metadata=request.metadata,
    )
    decision = _policy().evaluate(request)
    key = LLMCacheKeyFactory(secret="0123456789abcdef").build(
        request=request,
        context=decision.context,
        deployment_id="primary-v1",
        provider="test",
        model="model-v1",
    )
    with pytest.raises(CacheResponseValidationError):
        CacheEntry.from_response(
            key=key,
            request=request,
            response=LLMResponse(structured_output={"other": "value"}),
        )
