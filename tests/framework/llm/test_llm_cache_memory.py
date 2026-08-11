from __future__ import annotations

from framework.llm.cache import (
    CacheContext,
    CacheEntry,
    CacheLookupStatus,
    CacheScope,
    LLMCacheKeyFactory,
    InMemoryLLMCache,
)
from framework.llm.models import LLMRequest, LLMResponse


def _key(name: str):
    request = LLMRequest(messages=[{"role": "user", "content": name}], temperature=0)
    context = CacheContext(
        scope=CacheScope("tenant", "project", "policy"),
        semantic_metadata={"name": name},
    )
    return LLMCacheKeyFactory(secret="0123456789abcdef").build(
        request=request,
        context=context,
        deployment_id="deployment",
        provider="provider",
        model="model",
    ), request


def _entry(key, request, content: str) -> CacheEntry:
    return CacheEntry.from_response(
        key=key,
        request=request,
        response=LLMResponse(content=content),
        created_at=0,
    )


def test_memory_ttl_and_lru_are_bounded() -> None:
    now = [0.0]
    cache = InMemoryLLMCache(
        max_entries=2,
        max_bytes=10_000,
        clock=lambda: now[0],
        wall_clock=lambda: now[0],
    )
    key_a, request_a = _key("a")
    key_b, request_b = _key("b")
    key_c, request_c = _key("c")
    assert cache.put(key_a, _entry(key_a, request_a, "a"), ttl_seconds=10).stored
    assert cache.put(key_b, _entry(key_b, request_b, "b"), ttl_seconds=10).stored
    assert cache.get(key_a).status is CacheLookupStatus.HIT
    assert cache.put(key_c, _entry(key_c, request_c, "c"), ttl_seconds=10).stored
    assert cache.get(key_b).status is CacheLookupStatus.MISS
    now[0] = 11
    assert cache.get(key_a).status is CacheLookupStatus.EXPIRED
    assert cache.entry_count == 0


def test_memory_returns_isolated_entries_and_protects_lease_owner() -> None:
    now = [0.0]
    cache = InMemoryLLMCache(clock=lambda: now[0], wall_clock=lambda: now[0])
    key, request = _key("isolated")
    cache.put(key, _entry(key, request, "original"), ttl_seconds=10)
    first = cache.get(key)
    assert first.entry is not None
    first.entry.response["content"] = "mutated"
    assert cache.get(key).entry.response["content"] == "original"

    owner = cache.acquire_singleflight(key, owner_token="owner-token-1", ttl_seconds=1)
    assert owner.acquired and owner.lease is not None
    assert cache.acquire_singleflight(key, owner_token="owner-token-2", ttl_seconds=1).acquired is False
    now[0] = 2
    replacement = cache.acquire_singleflight(key, owner_token="owner-token-2", ttl_seconds=1)
    assert replacement.acquired and replacement.lease is not None
    assert cache.release_singleflight(owner.lease).released is False
    assert cache.release_singleflight(replacement.lease).released is True
