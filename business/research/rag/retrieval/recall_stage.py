from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.rag.core import intent_allowed

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval.channels.claim_index import ClaimIndexChannel
from business.research.rag.retrieval.channels.dense_text import DenseTextChannel
from business.research.rag.retrieval.channels.field_embedding import FieldEmbeddingChannel
from business.research.rag.retrieval.channels.sparse_lexical import SparseLexicalChannel, sparse_query_tokens
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.fusion import fuse_chunk_rankings
from business.research.rag.retrieval.paper_claim_index import ClaimSearchHit
from business.research.rag.retrieval.scoring import claim_from_citation_question
from business.research.rag.retrieval.trace import RetrievalTrace

_HYBRID_RRF_INTENTS = (
    "figure_query",
    "table_query",
    "numerical_result",
    "comparison",
    "formula_query",
    "citation_query",
)


@dataclass(frozen=True)
class CandidateRecallResult:
    candidates: list[tuple[PaperChunk, float]]
    field_hits: list[FieldEmbeddingHit]
    claim_hits: list[ClaimSearchHit]
    visual_hits: list[VisualChunkHit]
    n_recalled: int
    n_visual_recalled: int
    query_variants: list[str]


class CandidateRecallStage:
    def __init__(
        self,
        *,
        dense_channel: DenseTextChannel,
        sparse_channel: SparseLexicalChannel,
        field_channel: FieldEmbeddingChannel,
        claim_channel: ClaimIndexChannel,
        visual_channel: VisualRecallChannel,
        field_index: object | None,
        claim_index: object | None,
        visual_store: object | None,
        policy: Any,
    ) -> None:
        self._dense_channel = dense_channel
        self._sparse_channel = sparse_channel
        self._field_channel = field_channel
        self._claim_channel = claim_channel
        self._visual_channel = visual_channel
        self._field_index = field_index
        self._claim_index = claim_index
        self._visual_store = visual_store
        self._policy = policy

    def recall(
        self,
        request: Any,
        route: Any,
        candidate_filters: list[dict[str, Any]],
        candidate_limit: int,
        *,
        trace: RetrievalTrace,
    ) -> CandidateRecallResult:
        candidates = self._search_text_candidates(
            request,
            route,
            candidate_filters,
            candidate_limit,
            trace=trace,
        )
        n_recalled = len(candidates)
        field_hits = self._search_field_candidates(request, route, candidate_filters)
        candidates = self._field_channel.merge_hits(candidates, field_hits, request.paper_id)
        claim_hits = self._search_claim_candidates(request, route, limit=candidate_limit)
        candidates = self._claim_channel.merge_hits(candidates, claim_hits, request.paper_id)
        visual_hits = self._search_visual_candidates(request, route, candidate_filters)
        n_visual_recalled = len(visual_hits)
        if self._policy.hybrid_rrf_enabled and intent_allowed(route.intent, _HYBRID_RRF_INTENTS):
            candidates = self._fuse_hybrid_candidate_channels(
                candidates,
                field_hits=field_hits,
                claim_hits=claim_hits,
                visual_hits=visual_hits,
                paper_id=request.paper_id,
                limit=candidate_limit,
            )
        return CandidateRecallResult(
            candidates=candidates,
            field_hits=field_hits,
            claim_hits=claim_hits,
            visual_hits=visual_hits,
            n_recalled=n_recalled,
            n_visual_recalled=n_visual_recalled,
            query_variants=recall_queries_for_policy(request.question, route.intent, self._policy),
        )

    def _search_text_candidates(
        self,
        request: Any,
        route: Any,
        candidate_filters: list[dict[str, Any]],
        limit: int,
        *,
        trace: RetrievalTrace,
    ) -> list[tuple[PaperChunk, float]]:
        if self._policy.hybrid_rrf_enabled and intent_allowed(route.intent, _HYBRID_RRF_INTENTS):
            return self._search_hybrid_text_candidates(
                request,
                route,
                candidate_filters,
                limit,
                trace=trace,
            )
        by_id: dict[str, tuple[PaperChunk, float]] = {}
        query_texts = recall_queries_for_policy(request.question, route.intent, self._policy)
        for filters in candidate_filters:
            for query_text in query_texts:
                for chunk, score in self._dense_channel.recall_chunks(
                    paper_id=request.paper_id,
                    query_text=query_text,
                    filters=filters,
                    limit=limit,
                ):
                    existing = by_id.get(chunk.chunk_id)
                    if existing is None or score > existing[1]:
                        by_id[chunk.chunk_id] = (chunk, score)
        candidates = list(by_id.values())
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:limit]

    def _search_hybrid_text_candidates(
        self,
        request: Any,
        route: Any,
        candidate_filters: list[dict[str, Any]],
        limit: int,
        *,
        trace: RetrievalTrace,
    ) -> list[tuple[PaperChunk, float]]:
        rankings: list[tuple[str, list[tuple[PaperChunk, float]]]] = []
        query_texts = recall_queries_for_policy(request.question, route.intent, self._policy)
        for filter_index, filters in enumerate(candidate_filters):
            for query_index, query_text in enumerate(query_texts):
                semantic_hits = self._dense_channel.recall_chunks(
                    paper_id=request.paper_id,
                    query_text=query_text,
                    filters=filters,
                    limit=limit,
                    suppress_errors=True,
                )
                if semantic_hits:
                    rankings.append((f"semantic:{filter_index}:{query_index}", semantic_hits))
                if self._policy.sparse_lexical_enabled:
                    sparse_limit = max(limit, request.limit * self._policy.sparse_search_limit_multiplier)
                    sparse_hits = self._sparse_channel.recall_chunks(
                        paper_id=request.paper_id,
                        query_text=query_text,
                        filters=filters,
                        limit=sparse_limit,
                        formula_sparse_enabled=(
                            self._policy.formula_sparse_enabled and route.intent == "formula_query"
                        ),
                        trace=trace,
                    )
                    if sparse_hits:
                        rankings.append((f"sparse:{filter_index}:{query_index}", sparse_hits))
        return _rrf_fuse_rankings(
            rankings,
            limit=limit,
            rrf_k=self._policy.rrf_k,
            metadata_prefix="text",
        )

    def _search_field_candidates(
        self,
        request: Any,
        route: Any,
        candidate_filters: list[dict[str, Any]],
    ) -> list[FieldEmbeddingHit]:
        if self._field_index is None or not self._policy.field_embedding_enabled:
            return []
        limit = max(
            request.limit,
            request.limit
            * self._policy.overfetch_multiplier
            * max(1, self._policy.field_embedding_search_limit_multiplier),
        )
        return self._field_channel.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            field_names=self._policy.field_search_fields_for(route.intent),
            candidate_filters=candidate_filters,
            limit=limit,
        )

    def _search_claim_candidates(
        self,
        request: Any,
        route: Any,
        *,
        limit: int,
    ) -> list[ClaimSearchHit]:
        if self._claim_index is None or route.intent != "citation_query":
            return []
        return self._claim_channel.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            limit=limit,
        )

    def _search_visual_candidates(
        self,
        request: Any,
        route: Any,
        candidate_filters: list[dict[str, Any]],
    ) -> list[VisualChunkHit]:
        if self._visual_store is None or route.intent != "figure_query":
            return []
        limit = request.limit * self._policy.overfetch_multiplier
        return self._visual_channel.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            candidate_filters=candidate_filters,
            limit=limit,
        )

    def _fuse_hybrid_candidate_channels(
        self,
        candidates: list[tuple[PaperChunk, float]],
        *,
        field_hits: list[FieldEmbeddingHit],
        claim_hits: list[ClaimSearchHit],
        visual_hits: list[VisualChunkHit],
        paper_id: str,
        limit: int,
    ) -> list[tuple[PaperChunk, float]]:
        rankings: list[tuple[str, list[tuple[PaperChunk, float]]]] = []
        if candidates:
            ranked_candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
            rankings.append(("text_sparse", ranked_candidates))
        field_ranked = self._field_channel.ranked_chunks(field_hits, paper_id)
        if field_ranked:
            rankings.append(("field_embedding", field_ranked))
        claim_ranked = self._claim_channel.ranked_chunks(claim_hits, paper_id)
        if claim_ranked:
            rankings.append(("claim", claim_ranked))
        visual_ranked = self._visual_channel.ranked_chunks(visual_hits, paper_id)
        if visual_ranked:
            rankings.append(("visual", visual_ranked))
        if len(rankings) <= 1:
            return candidates
        return _rrf_fuse_rankings(
            rankings,
            limit=limit,
            rrf_k=self._policy.rrf_k,
            metadata_prefix="hybrid",
        )


def recall_queries_for_policy(question: str, intent: str, policy: Any) -> list[str]:
    queries = _text_recall_queries(question, intent)
    if not policy.multi_query_enabled:
        return queries
    sparse_terms = " ".join(sparse_query_tokens(question))
    if sparse_terms:
        queries.append(sparse_terms)
    intent_suffixes = {
        "figure_query": "figure caption visual description referenced paragraph",
        "table_query": "table caption rows columns result paragraph",
        "formula_query": "equation formula latex symbols explanation",
        "numerical_result": "experiment results table conclusion analysis",
        "comparison": "comparison baseline versus table result",
        "citation_query": "supporting evidence claim grounded passage",
        "contribution": "abstract contribution method novelty",
    }
    suffix = intent_suffixes.get(intent, "")
    if suffix and sparse_terms:
        queries.append(f"{sparse_terms} {suffix}")
    elif suffix:
        queries.append(f"{question} {suffix}")
    return _unique_nonempty_texts(queries)


def _text_recall_queries(question: str, intent: str) -> list[str]:
    queries = [str(question or "")]
    if intent == "citation_query":
        claim = claim_from_citation_question(question)
        if claim:
            queries.append(claim)
    return _unique_nonempty_texts(queries)


def _rrf_fuse_rankings(
    rankings: list[tuple[str, list[tuple[PaperChunk, float]]]],
    *,
    limit: int,
    rrf_k: int,
    metadata_prefix: str,
) -> list[tuple[PaperChunk, float]]:
    return fuse_chunk_rankings(
        rankings,
        limit=limit,
        rrf_k=rrf_k,
        metadata_prefix=metadata_prefix,
    )


def _unique_nonempty_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


__all__ = ["CandidateRecallResult", "CandidateRecallStage", "recall_queries_for_policy"]
