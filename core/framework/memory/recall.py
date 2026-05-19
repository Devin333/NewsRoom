from __future__ import annotations

from typing import Protocol

from core.framework.memory.models import (
    MemoryContextBlock,
    MemoryQuery,
    MemoryRecallResult,
    MemorySearchResult,
    estimate_tokens,
)
from core.framework.memory.policy import MemoryPolicy
from core.framework.memory.store import MemoryStore


class MemoryRecallStrategy(Protocol):
    def recall(
        self,
        query: MemoryQuery,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        assembler: "MemoryContextAssembler",
    ) -> MemoryRecallResult:
        ...


class SimpleMemoryRecallStrategy:
    def recall(
        self,
        query: MemoryQuery,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        assembler: "MemoryContextAssembler",
    ) -> MemoryRecallResult:
        policy.validate_recall(query)
        effective_query = policy.filtered_query(query)
        results = store.search(effective_query)
        results = _rank_filter_and_limit(results, effective_query)
        context_budget = effective_query.max_context_tokens or policy.max_context_tokens
        context_block = assembler.assemble(
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
        entries: list[str] = []
        memory_ids: list[str] = []
        for result in results:
            block = _format_memory_entry(result, index=len(entries) + 1)
            candidate_entries = [*entries, block]
            candidate_content = _wrap_memory_context(candidate_entries)
            tokens = estimate_tokens(candidate_content)
            if entries and tokens > max_context_tokens:
                break
            if not entries and tokens > max_context_tokens:
                candidate_content = _truncate_to_token_budget(candidate_content, max_context_tokens)
                tokens = estimate_tokens(candidate_content)
            entries.append(block)
            memory_ids.append(result.record.memory_id)
            if len(entries) == 1 and tokens > max_context_tokens:
                break
        content = _wrap_memory_context(entries) if entries else ""
        if content and estimate_tokens(content) > max_context_tokens:
            content = _truncate_to_token_budget(content, max_context_tokens)
        return MemoryContextBlock(
            content=content,
            token_estimate=estimate_tokens(content),
            memory_ids=memory_ids,
        )


def _rank_filter_and_limit(
    results: list[MemorySearchResult],
    query: MemoryQuery,
) -> list[MemorySearchResult]:
    filtered = [
        result
        for result in results
        if query.min_score is None or result.score >= query.min_score
    ]
    filtered.sort(key=lambda result: result.score, reverse=True)
    return filtered[: query.limit]


def _truncate_to_token_budget(text: str, max_context_tokens: int) -> str:
    char_budget = max(16, max_context_tokens * 4)
    if len(text) <= char_budget:
        return text
    return text[: char_budget - 3] + "..."


def _wrap_memory_context(entries: list[str]) -> str:
    if not entries:
        return ""
    body = "\n\n".join(entries)
    return f"<memory_context>\nRelevant memories:\n{body}\n</memory_context>"


def _format_memory_entry(result: MemorySearchResult, *, index: int) -> str:
    record = result.record
    confidence = _score_text(record.confidence)
    importance = _score_text(record.importance)
    summary = record.summary or record.content
    refs = _safe_refs_text(record.refs)
    refs_line = f"\n   refs: {refs}" if refs else ""
    return (
        f"{index}. [{record.kind.value} | confidence={confidence} | importance={importance}]\n"
        f"   summary: {summary}\n"
        f"   memory_id: {record.memory_id} | source={result.source} | score={result.score:.3f}"
        f"{refs_line}\n"
        f"   content: {record.content}"
    )


def _score_text(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


_SAFE_REF_KEYS = {
    "artifact_id",
    "evidence_id",
    "report_id",
    "run_id",
    "section_id",
    "source_id",
    "source_item_id",
    "source_item_ids",
    "step_id",
    "workflow_id",
}


def _safe_refs_text(refs: dict[str, object]) -> str:
    safe_items = [
        f"{key}={refs[key]}"
        for key in sorted(refs)
        if key in _SAFE_REF_KEYS and refs.get(key) is not None
    ]
    return ", ".join(safe_items)


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
