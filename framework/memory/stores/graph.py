from __future__ import annotations

from typing import Protocol

from framework.memory.models import MemoryQuery, MemorySearchResult


class GraphMemoryStore(Protocol):
    def relation_search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...

__all__ = ["GraphMemoryStore"]
