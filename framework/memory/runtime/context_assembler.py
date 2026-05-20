from __future__ import annotations

from framework.memory.context import (
    MemoryCitationBuilder,
    MemoryContextBudget,
    MemoryContextCompressor,
    MemoryContextFormatter,
)
from framework.memory.models import MemoryContextBlock, MemorySearchResult, estimate_tokens


class MemoryContextAssembler:
    def __init__(
        self,
        formatter: MemoryContextFormatter | None = None,
        budget: MemoryContextBudget | None = None,
        citation_builder: MemoryCitationBuilder | None = None,
        compressor: MemoryContextCompressor | None = None,
    ) -> None:
        self.formatter = formatter or MemoryContextFormatter()
        self.budget = budget
        self.citation_builder = citation_builder or MemoryCitationBuilder()
        self.compressor = compressor or MemoryContextCompressor()

    def assemble(
        self,
        results: list[MemorySearchResult],
        *,
        max_context_tokens: int | None = None,
    ) -> MemoryContextBlock:
        budget = self.budget or MemoryContextBudget(max_context_tokens or 2000)
        entries: list[str] = []
        memory_ids: list[str] = []
        for result in results:
            block = self.formatter.format_entry(result, index=len(entries) + 1)
            candidate_entries = [*entries, block]
            candidate_content = self.formatter.wrap(candidate_entries)
            tokens = estimate_tokens(candidate_content)
            if entries and tokens > budget.max_tokens:
                break
            if not entries and tokens > budget.max_tokens:
                candidate_content = self.compressor.compress(candidate_content, max_tokens=budget.max_tokens)
                tokens = estimate_tokens(candidate_content)
            entries.append(block)
            memory_ids.append(result.record.memory_id)
            if len(entries) == 1 and tokens > budget.max_tokens:
                break
        content = self.formatter.wrap(entries) if entries else ""
        if content and estimate_tokens(content) > budget.max_tokens:
            content = self.compressor.compress(content, max_tokens=budget.max_tokens)
        return MemoryContextBlock(
            content=content,
            token_estimate=estimate_tokens(content),
            memory_ids=memory_ids,
            citations=self.citation_builder.citations_for(results[: len(memory_ids)]),
        )
