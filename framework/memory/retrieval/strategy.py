from __future__ import annotations

from typing import Protocol

from framework.memory.models import MemoryQuery, MemorySearchResult
from framework.memory.stores import MemoryStore


class MemoryRetrievalStrategy(Protocol):
    def search(self, query: MemoryQuery, *, store: MemoryStore) -> list[MemorySearchResult]:
        ...


class MemoryRecallStrategy(Protocol):
    def recall(self, *args, **kwargs):
        ...
