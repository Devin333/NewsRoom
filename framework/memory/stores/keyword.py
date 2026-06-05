from __future__ import annotations

from typing import Protocol

from framework.memory.models import MemoryQuery, MemorySearchResult


class KeywordMemoryStore(Protocol):
    def keyword_search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...

__all__ = ["KeywordMemoryStore"]
