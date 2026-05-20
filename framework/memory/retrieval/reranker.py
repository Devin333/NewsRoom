from __future__ import annotations

from framework.memory.models import MemorySearchResult


class MemoryReranker:
    def rerank(self, results: list[MemorySearchResult]) -> list[MemorySearchResult]:
        return sorted(results, key=lambda result: result.score, reverse=True)
