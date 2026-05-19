from __future__ import annotations

from core.framework.memory.models import (
    MemoryContextBlock,
    MemoryQuery,
    MemoryRecallResult,
    MemorySearchResult,
    estimate_tokens,
)
from core.framework.memory.policy import MemoryPolicy
from core.framework.memory.store import MemoryStore


class SimpleMemoryRecallStrategy:
    def recall(
        self,
        query: MemoryQuery,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
    ) -> MemoryRecallResult:
        policy.validate_recall(query)
        effective_query = policy.filtered_query(query)
        results = store.search(effective_query)
        context_budget = effective_query.max_context_tokens or policy.max_context_tokens
        context_block = MemoryContextAssembler().assemble(
            results,
            max_context_tokens=context_budget,
        )
        return MemoryRecallResult(
            query=effective_query,
            results=results,
            context_block=context_block,
            diagnostics=_recall_diagnostics(
                requested_query=query,
                effective_query=effective_query,
                results=results,
                context_block=context_block,
                context_budget=context_budget,
            ),
        )


class MemoryContextAssembler:
    def assemble(
        self,
        results: list[MemorySearchResult],
        *,
        max_context_tokens: int,
    ) -> MemoryContextBlock:
        lines: list[str] = []
        memory_ids: list[str] = []
        token_total = 0
        for result in results:
            record = result.record
            label = record.summary or record.content[:120]
            block = (
                f"- [{record.kind.value}/{record.scope.value}] "
                f"{label}\n"
                f"  memory_id={record.memory_id} score={result.score:.3f}\n"
                f"  {record.content}"
            )
            tokens = estimate_tokens(block)
            if lines and token_total + tokens > max_context_tokens:
                break
            if not lines and tokens > max_context_tokens:
                block = _truncate_to_token_budget(block, max_context_tokens)
                tokens = estimate_tokens(block)
            lines.append(block)
            memory_ids.append(record.memory_id)
            token_total += tokens
        return MemoryContextBlock(
            content="\n".join(lines),
            token_estimate=token_total,
            memory_ids=memory_ids,
        )


def _truncate_to_token_budget(text: str, max_context_tokens: int) -> str:
    char_budget = max(16, max_context_tokens * 4)
    if len(text) <= char_budget:
        return text
    return text[: char_budget - 3] + "..."


def _recall_diagnostics(
    *,
    requested_query: MemoryQuery,
    effective_query: MemoryQuery,
    results: list[MemorySearchResult],
    context_block: MemoryContextBlock,
    context_budget: int,
) -> dict[str, object]:
    return {
        "requested_query": requested_query.to_dict(),
        "effective_query": effective_query.to_dict(),
        "result_count": len(results),
        "context_token_budget": context_budget,
        "context_token_estimate": context_block.token_estimate,
        "memory_ids": list(context_block.memory_ids),
    }
