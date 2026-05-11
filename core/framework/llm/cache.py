from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Callable

from core.framework.llm.models import LLMClient, LLMRequest, LLMResponse


Clock = Callable[[], float]


@dataclass(frozen=True)
class LLMCachePolicy:
    enabled: bool = False
    ttl_seconds: float | None = None
    cacheable_task_types: tuple[str, ...] = ()
    no_cache_agent_ids: tuple[str, ...] = ()

    def allows(self, request: LLMRequest) -> bool:
        if not self.enabled:
            return False
        agent_id = request.metadata.get("agent_id")
        if agent_id in self.no_cache_agent_ids:
            return False
        task_type = request.metadata.get("task_type")
        return isinstance(task_type, str) and task_type in self.cacheable_task_types


@dataclass(frozen=True)
class LLMCacheKey:
    provider: str
    model: str
    digest: str

    @classmethod
    def from_request(cls, *, provider: str, model: str, request: LLMRequest) -> LLMCacheKey:
        payload = {
            "provider": provider,
            "model": model,
            "request": request.to_dict(redact=False),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return cls(provider=provider, model=model, digest=hashlib.sha256(encoded).hexdigest())

    def to_string(self) -> str:
        return f"{self.provider}:{self.model}:{self.digest}"


@dataclass(frozen=True)
class _CacheEntry:
    response: LLMResponse
    created_at: float


class InMemoryLLMCache:
    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or time.time
        self._entries: dict[str, _CacheEntry] = {}

    def get(self, key: LLMCacheKey, *, ttl_seconds: float | None = None) -> LLMResponse | None:
        cache_key = key.to_string()
        entry = self._entries.get(cache_key)
        if entry is None:
            return None
        if ttl_seconds is not None and self._clock() - entry.created_at > ttl_seconds:
            self._entries.pop(cache_key, None)
            return None
        return deepcopy(entry.response)

    def set(self, key: LLMCacheKey, response: LLMResponse) -> None:
        self._entries[key.to_string()] = _CacheEntry(
            response=deepcopy(response),
            created_at=self._clock(),
        )


class CachedLLMClient:
    def __init__(
        self,
        client: LLMClient,
        *,
        provider: str,
        model: str,
        policy: LLMCachePolicy,
        cache: InMemoryLLMCache | None = None,
    ) -> None:
        self._client = client
        self._provider = provider
        self._model = model
        self._policy = policy
        self._cache = cache or InMemoryLLMCache()

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self._policy.allows(request):
            return self._mark_cache_metadata(self._client.complete(request), cacheable=False, hit=False)

        cache_key = LLMCacheKey.from_request(provider=self._provider, model=self._model, request=request)
        cached_response = self._cache.get(cache_key, ttl_seconds=self._policy.ttl_seconds)
        if cached_response is not None:
            return self._mark_cache_metadata(cached_response, cacheable=True, hit=True)

        response = self._client.complete(request)
        self._cache.set(cache_key, response)
        return self._mark_cache_metadata(response, cacheable=True, hit=False)

    def _mark_cache_metadata(self, response: LLMResponse, *, cacheable: bool, hit: bool) -> LLMResponse:
        metadata = dict(response.metadata)
        metadata.update(
            {
                "llm_cacheable": cacheable,
                "llm_cache_hit": hit,
            }
        )
        return replace(response, metadata=metadata)
