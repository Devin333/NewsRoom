from __future__ import annotations

from framework.memory.models import MemorySearchResult


class MemoryCitationBuilder:
    def citation_for(self, result: MemorySearchResult) -> str:
        return result.memory_id

    def citations_for(self, results: list[MemorySearchResult]) -> list[str]:
        return [self.citation_for(result) for result in results]
