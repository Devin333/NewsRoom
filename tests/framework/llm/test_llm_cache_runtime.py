from __future__ import annotations

import pytest

from framework.llm.cache import (
    CacheEntry,
    CacheLookupStatus,
    CacheMode,
    InMemoryLLMCache,
    LLMCacheKeyFactory,
    LLMCachePolicy,
    LLMCacheRuntime,
    SingleFlightAcquireStatus,
)
from framework.llm.models import LLMRequest, LLMResponse


def _request(*, deadline_monotonic: float | None = None) -> LLMRequest:
    envelope: dict[str, object] = {
        "scope": {
            "tenant_id": "tenant",
            "project_id": "project",
            "policy_scope": "policy",
        },
        "dependencies": {"prompt_revision": "v1"},
    }
    if deadline_monotonic is not None:
        envelope["deadline_monotonic"] = deadline_monotonic
    return LLMRequest(
        messages=[{"role": "user", "content": "stable"}],
        temperature=0,
        metadata={"task_type": "classify", "llm_cache": envelope},
    )


def _runtime(
    cache: InMemoryLLMCache,
    *,
    clock,
    sleep,
    wait_timeout_ms: int = 1_000,
    poll_interval_ms: int = 100,
) -> LLMCacheRuntime:
    return LLMCacheRuntime(
        policy=LLMCachePolicy(
            mode=CacheMode.READ_WRITE,
            cacheable_task_types=("classify",),
            required_dependencies=("prompt_revision",),
        ),
        key_factory=LLMCacheKeyFactory(secret="0123456789abcdef"),
        store=cache,
        coordinator=cache,
        singleflight_wait_timeout_ms=wait_timeout_ms,
        singleflight_poll_interval_ms=poll_interval_ms,
        clock=clock,
        sleep=sleep,
        owner_token_factory=lambda: "waiter-owner-token-0001",
    )


def test_busy_singleflight_waiter_rechecks_and_returns_owner_entry() -> None:
    now = [0.01]
    cache = InMemoryLLMCache(clock=lambda: now[0], wall_clock=lambda: now[0])
    request = _request()
    published = [False]
    runtime: LLMCacheRuntime

    def sleep(seconds: float) -> None:
        now[0] += seconds
        if not published[0]:
            preparation = runtime.prepare(
                request=request,
                deployment_id="deployment",
                provider="provider",
                model="model",
            )
            assert preparation.key is not None
            entry = CacheEntry.from_response(
                key=preparation.key,
                request=request,
                response=LLMResponse(content="owner result"),
                created_at=now[0],
            )
            assert cache.put(preparation.key, entry, ttl_seconds=60).stored
            published[0] = True

    runtime = _runtime(cache, clock=lambda: now[0], sleep=sleep)
    preparation = runtime.prepare(
        request=request,
        deployment_id="deployment",
        provider="provider",
        model="model",
    )
    assert preparation.key is not None
    owner = cache.acquire_singleflight(
        preparation.key,
        owner_token="current-owner-token-0001",
        ttl_seconds=10,
    )
    assert owner.acquired

    admission = runtime.admit_singleflight(preparation)
    waited = runtime.wait_for_entry(preparation, request=request)

    assert admission.result.status is SingleFlightAcquireStatus.BUSY
    assert admission.write_authorized is False
    assert waited.hit
    assert waited.response is not None
    assert waited.response.content == "owner result"


def test_singleflight_wait_stops_at_caller_deadline_without_oversleeping() -> None:
    now = [0.01]
    sleeps: list[float] = []
    cache = InMemoryLLMCache(clock=lambda: now[0], wall_clock=lambda: now[0])

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    runtime = _runtime(cache, clock=lambda: now[0], sleep=sleep)
    request = _request(deadline_monotonic=0.13)
    preparation = runtime.prepare(
        request=request,
        deployment_id="deployment",
        provider="provider",
        model="model",
    )

    waited = runtime.wait_for_entry(preparation, request=request)

    assert waited.lookup.status is CacheLookupStatus.MISS
    assert waited.lookup.reason == "singleflight_wait_timeout"
    assert sum(sleeps) == pytest.approx(0.12)
    assert now[0] == pytest.approx(0.13)
    assert max(sleeps) <= 0.1
