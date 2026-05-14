from core.framework.llm import (
    CachedLLMClient,
    InMemoryLLMCache,
    LLMCacheKey,
    LLMCachePolicy,
    LLMRequest,
    LLMResponse,
)


def test_cache_key_exposes_digest_not_raw_prompt() -> None:
    request = LLMRequest(
        messages=[{"role": "user", "content": "private prompt"}],
        metadata={"task_type": "classification"},
    )

    key = LLMCacheKey.from_request(provider="test", model="model", request=request)

    assert len(key.digest) == 64
    assert "private prompt" not in key.to_string()
    assert key.to_string().startswith("test:model:")


def test_cached_llm_client_serves_allowed_task_from_cache() -> None:
    inner = CountingClient()
    cached = CachedLLMClient(
        inner,
        provider="test",
        model="model",
        policy=LLMCachePolicy(enabled=True, cacheable_task_types=("classification",)),
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "classify"}],
        metadata={"task_type": "classification"},
    )

    first = cached.complete(request)
    second = cached.complete(request)

    assert inner.call_count == 1
    assert first.content == "response-1"
    assert first.metadata["llm_cache_hit"] is False
    assert first.metadata["llm_budget_cost_counted"] is True
    assert second.content == "response-1"
    assert second.metadata["llm_cache_hit"] is True
    assert second.metadata["llm_cacheable"] is True
    assert second.metadata["llm_budget_cost_counted"] is False
    assert second.metadata["llm_budget_request_counted"] is True


def test_cached_llm_client_bypasses_unlisted_task_type() -> None:
    inner = CountingClient()
    cached = CachedLLMClient(
        inner,
        provider="test",
        model="model",
        policy=LLMCachePolicy(enabled=True, cacheable_task_types=("classification",)),
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "write"}],
        metadata={"task_type": "final_report"},
    )

    first = cached.complete(request)
    second = cached.complete(request)

    assert inner.call_count == 2
    assert first.content == "response-1"
    assert second.content == "response-2"
    assert second.metadata["llm_cacheable"] is False


def test_cached_llm_client_bypasses_denied_agent() -> None:
    inner = CountingClient()
    cached = CachedLLMClient(
        inner,
        provider="test",
        model="model",
        policy=LLMCachePolicy(
            enabled=True,
            cacheable_task_types=("classification",),
            no_cache_agent_ids=("writer",),
        ),
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "classify"}],
        metadata={"task_type": "classification", "agent_id": "writer"},
    )

    cached.complete(request)
    cached.complete(request)

    assert inner.call_count == 2


def test_in_memory_llm_cache_expires_entries_after_ttl() -> None:
    now = [100.0]
    cache = InMemoryLLMCache(clock=lambda: now[0])
    key = LLMCacheKey.from_request(
        provider="test",
        model="model",
        request=LLMRequest(messages=[{"role": "user", "content": "classify"}]),
    )
    cache.set(key, LLMResponse(content="cached"))

    assert cache.get(key, ttl_seconds=10).content == "cached"

    now[0] = 111.0

    assert cache.get(key, ttl_seconds=10) is None


class CountingClient:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(content=f"response-{self.call_count}")
