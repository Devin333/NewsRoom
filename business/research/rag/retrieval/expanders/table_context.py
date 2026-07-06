from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from framework.rag.retrieval import RerankScoreSet, expansion_metadata, rerank_sort_key

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.rag.retrieval.filtering import merge_request_filters

if TYPE_CHECKING:
    from business.research.ports.reranker import RerankerPort

_TABLE_EXPANSION_INTENTS = frozenset({"table_query", "numerical_result", "comparison"})
_RESULT_SECTION_ROLES = frozenset({"experiment", "analysis", "conclusion"})
_RESULT_CONTEXT_KEYWORDS = (
    "sample quality",
    "result",
    "results",
    "experiment",
    "experiments",
    "evaluation",
    "ablation",
    "analysis",
    "conclusion",
    "benchmark",
    "quality",
    "accuracy",
    "fid",
    "inception score",
    "likelihood",
    "codelength",
    "bits/dim",
    "score",
)
_RESULT_QUESTION_KEYWORDS = (
    "result",
    "results",
    "experiment",
    "experiments",
    "accuracy",
    "f1",
    "score",
    "ablation",
    "\u5b9e\u9a8c\u7ed3\u679c",
    "\u7ed3\u679c",
    "\u8868\u660e",
)


class TableContextExpander:
    name = "table_context"

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        policy: Any,
        *,
        reranker: "RerankerPort | None" = None,
    ) -> None:
        self._store = chunk_store
        self._policy = policy
        self._reranker = reranker

    def expand(self, chunks: list[PaperChunk], request: Any, route: Any) -> list[PaperChunk]:
        table_hits = [chunk for chunk in chunks if _is_table_chunk(chunk)]
        if not table_hits:
            return []

        seen = {chunk.chunk_id for chunk in chunks}
        out: list[PaperChunk] = []
        include_result_context = should_expand_result_context(route.intent, request.question)

        for table in table_hits:
            added_for_table = 0
            expansion_rank = 0

            def add_chunk(chunk: PaperChunk | None, *, reason: str, edge: str) -> None:
                nonlocal added_for_table, expansion_rank
                if added_for_table >= self._policy.max_table_context_chunks:
                    return
                if chunk is None or chunk.paper_id != request.paper_id or chunk.chunk_id in seen:
                    return
                seen.add(chunk.chunk_id)
                added_for_table += 1
                expansion_rank += 1
                out.append(_with_expansion_metadata(
                    chunk,
                    expanded_from_chunk_id=table.chunk_id,
                    reason=reason,
                    edge=edge,
                    rank=expansion_rank,
                    source_chunk=table,
                ))

            nearby_id = str(table.metadata.get("nearby_context_chunk_id") or "")
            add_chunk(
                self._store.get_chunk(nearby_id) if nearby_id else None,
                reason="table_nearby_context",
                edge="nearby_context_chunk_id",
            )

            for ref in table.metadata.get("referenced_by_chunks", []):
                if not isinstance(ref, dict):
                    continue
                ref_id = str(ref.get("chunk_id") or "")
                add_chunk(
                    self._store.get_chunk(ref_id) if ref_id else None,
                    reason="table_body_reference",
                    edge="referenced_by_chunks",
                )

            parent_table_id = str(table.metadata.get("parent_table_chunk_id") or "")
            add_chunk(
                self._store.get_chunk(parent_table_id) if parent_table_id else None,
                reason="table_row_group_parent",
                edge="parent_table_chunk_id",
            )

            parent_id = table.parent_chunk_id or ""
            add_chunk(
                self._store.get_chunk(parent_id) if parent_id else None,
                reason="table_parent_context",
                edge="parent_chunk_id",
            )

            if not include_result_context:
                continue
            remaining = self._policy.max_table_context_chunks - added_for_table
            if remaining <= 0:
                continue
            for chunk in self._result_context_candidates(table, request, seen, limit=remaining):
                add_chunk(
                    chunk,
                    reason="table_result_context",
                    edge="section_role_or_title",
                )

        return out

    def _result_context_candidates(
        self,
        table: PaperChunk,
        request: Any,
        seen: set[str],
        *,
        limit: int,
    ) -> list[PaperChunk]:
        if limit <= 0:
            return []
        query_text = f"{request.question}\n{table.section_title}\n{table.content[:1000]}"
        try:
            scored = self._store.search_with_scores(
                request.paper_id,
                query_text,
                filters=merge_request_filters(request, {"chunk_type": "paragraph"}),
                limit=self._policy.table_result_context_search_limit,
            )
        except Exception:
            logging.getLogger(__name__).warning("table result context retrieval failed", exc_info=True)
            return []

        candidates: list[tuple[tuple[int, int, int], float, PaperChunk]] = []
        for chunk, score in scored:
            if chunk.paper_id != request.paper_id or chunk.chunk_id in seen:
                continue
            priority = _result_context_priority(chunk, table)
            if priority is None:
                continue
            candidates.append((priority, score, chunk))
        if self._reranker is not None:
            reranked = self._rerank_table_result_context(table, request, candidates, limit=limit)
            if reranked:
                return reranked
        candidates.sort(key=lambda item: (*item[0], -item[1]))
        return [chunk for _priority, _score, chunk in candidates[:limit]]

    def _rerank_table_result_context(
        self,
        table: PaperChunk,
        request: Any,
        candidates: list[tuple[tuple[int, int, int], float, PaperChunk]],
        *,
        limit: int,
    ) -> list[PaperChunk]:
        if not candidates:
            return []
        query_text = _table_context_rerank_query(table, request)
        try:
            scores = self._reranker.score(  # type: ignore[union-attr]
                query_text,
                [chunk.content for _priority, _vector_score, chunk in candidates],
            )
        except Exception:
            logging.getLogger(__name__).warning("table context reranker failed", exc_info=True)
            return []
        normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(candidates))
        if normalized_scores is None:
            logging.getLogger(__name__).warning(
                "table context reranker returned %s scores for %s candidates",
                len(scores),
                len(candidates),
            )
            return []

        ranked: list[tuple[float, tuple[int, int, int], float, PaperChunk]] = []
        for rerank_score, (priority, vector_score, chunk) in zip(normalized_scores.scores, candidates, strict=True):
            if rerank_score < self._policy.table_context_rerank_score_threshold:
                continue
            metadata = dict(chunk.metadata)
            metadata.update({
                "table_context_rerank_score": round(rerank_score, 6),
                "table_context_rerank_strategy": "cross_encoder",
                "table_context_rerank_query": query_text[:400],
            })
            ranked.append((
                float(rerank_score),
                priority,
                vector_score,
                chunk.model_copy(update={"metadata": metadata}),
            ))
        ranked.sort(key=lambda item: rerank_sort_key(
            rerank_score=item[0],
            priority=item[1],
            fallback_score=item[2],
        ))
        return [chunk for _rerank, _priority, _vector_score, chunk in ranked[:limit]]


def should_expand_result_context(intent: str, question: str) -> bool:
    if intent in _TABLE_EXPANSION_INTENTS:
        return True
    normalized = question.casefold()
    return any(keyword in normalized for keyword in _RESULT_QUESTION_KEYWORDS)


def _is_table_chunk(chunk: PaperChunk) -> bool:
    return (
        chunk.chunk_type == "table"
        or chunk.has_table
        or bool(chunk.metadata.get("table_id"))
        or bool(chunk.metadata.get("parent_table_chunk_id"))
    )


def _result_context_priority(chunk: PaperChunk, table: PaperChunk) -> tuple[int, int, int] | None:
    if chunk.chunk_type != "paragraph":
        return None
    role_rank = _result_role_rank(chunk)
    title_rank = _result_title_rank(chunk.section_title)
    content_rank = _result_title_rank(chunk.content[:240])
    semantic_rank = min(title_rank, content_rank)
    if semantic_rank >= 100:
        return None
    section_distance = abs(chunk.section_index - table.section_index)
    proximity_rank = 0 if section_distance == 0 else 1 if section_distance == 1 else 2
    role_bonus = 0 if role_rank < 100 else 1
    return proximity_rank, semantic_rank + role_bonus, section_distance


def _result_role_rank(chunk: PaperChunk) -> int:
    ranks = {"experiment": 0, "analysis": 1, "conclusion": 2}
    values = [
        ranks.get(str(role).casefold(), 100)
        for role in chunk.section_role
        if str(role).casefold() in _RESULT_SECTION_ROLES
    ]
    return min(values) if values else 100


def _result_title_rank(text: str) -> int:
    normalized = text.casefold()
    for index, keyword in enumerate(_RESULT_CONTEXT_KEYWORDS):
        if keyword in normalized:
            return index
    return 100


def _table_context_rerank_query(table: PaperChunk, request: Any) -> str:
    table_text = " ".join(table.content.split())
    return "\n".join([
        request.question.strip(),
        f"Table section: {table.section_title}",
        f"Table evidence: {table_text[:1000]}",
    ]).strip()


def _with_expansion_metadata(
    chunk: PaperChunk,
    *,
    expanded_from_chunk_id: str,
    reason: str,
    edge: str,
    rank: int,
    source_chunk: PaperChunk | None = None,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    _preserve_source_locator(metadata, source_chunk)
    metadata["graph_score"] = max(_metadata_float(metadata, "graph_score", 0.0), 1.0)
    metadata.update(expansion_metadata(
        expanded_from_id=expanded_from_chunk_id,
        reason=reason,
        edge=edge,
        rank=rank,
    ))
    return chunk.model_copy(update={"metadata": metadata})


def _preserve_source_locator(metadata: dict[str, Any], source_chunk: PaperChunk | None) -> None:
    if source_chunk is None:
        return
    if metadata.get("source_locator"):
        return
    source_locator = str(
        source_chunk.metadata.get("source_locator")
        or source_chunk.metadata.get("source_ref")
        or ""
    )
    if not source_locator:
        return
    metadata["source_locator"] = source_locator
    metadata["source_locator_inherited"] = True
    metadata["source_locator_origin_chunk_id"] = source_chunk.chunk_id
    source_locators = source_chunk.metadata.get("source_locators")
    if source_locators and not metadata.get("source_locators"):
        metadata["source_locators"] = source_locators


def _metadata_float(metadata: dict[str, Any], key: str, default: float) -> float:
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["TableContextExpander", "should_expand_result_context"]
