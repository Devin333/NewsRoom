from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from framework.llm.cache.key import LLMCacheKey
from framework.llm.models.response import LLMResponse


Clock = Callable[[], float]


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

