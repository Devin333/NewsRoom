from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from framework.rag.retrieval import dedupe_by_key

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval.paper_policy import QueryIntent, RetrievalRoute
from business.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    with_retrieval_scores,
)
from business.research.rag.retrieval.policy_config import policy_config_hash
from business.research.rag.retrieval.scoring import ChildCandidateScorer, round_score
from business.research.rag.retrieval.trace import RetrievalTrace

_FORMULA_CONTEXT_REASONS = frozenset({
    "formula_nearby_context",
    "formula_explained_by",
    "formula_body_reference",
    "formula_explicit_reference",
    "formula_parent_context",
    "formula_reverse_context",
    "formula_reverse_reference",
})


class RetrievalPipeline:
    def __init__(
        self,
        *,
        policy: Any,
        planner: Any,
        recall_stage: Any,
        rerank_cascade: Any,
        child_scorer: ChildCandidateScorer,
        visual_channel: Any,
        parent_expander: Any,
        cross_ref_expander: Any,
        table_context_expander: Any,
        structural_expander: Any,
        supplemental_table_expander: Any,
        request_factory: Callable[..., Any],
        result_factory: Callable[..., Any],
        reranker_available: bool,
        field_index_available: bool,
        field_reranker_available: bool,
        visual_store_available: bool,
        claim_index_available: bool,
    ) -> None:
        self._policy = policy
        self._planner = planner
        self._recall_stage = recall_stage
        self._rerank_cascade = rerank_cascade
        self._child_scorer = child_scorer
        self._visual_channel = visual_channel
        self._parent_expander = parent_expander
        self._cross_ref_expander = cross_ref_expander
        self._table_context_expander = table_context_expander
        self._structural_expander = structural_expander
        self._supplemental_table_expander = supplemental_table_expander
        self._request_factory = request_factory
        self._result_factory = result_factory
        self._reranker_available = reranker_available
        self._field_index_available = field_index_available
        self._field_reranker_available = field_reranker_available
        self._visual_store_available = visual_store_available
        self._claim_index_available = claim_index_available

    def retrieve(self, request: Any) -> Any:
        t0 = time.perf_counter()
        plan = self._planner.build(request)
        route = plan.route
        candidate_filters = [dict(item) for item in plan.candidate_filters]
        active_policy_hash = policy_config_hash(self._policy)
        retrieval_trace = RetrievalTrace(
            policy_name=self._policy.name,
            policy_hash=active_policy_hash,
            route=plan.route_dict(),
        )

        element_query_labels = set(plan.element_query_labels)
        candidate_limit = plan.candidate_limit
        recall_result = self._recall_stage.recall(
            request,
            route,
            candidate_filters,
            candidate_limit,
            trace=retrieval_trace,
        )
        candidates = recall_result.candidates
        field_hits = recall_result.field_hits
        claim_hits = recall_result.claim_hits
        visual_hits = recall_result.visual_hits
        n_recalled = recall_result.n_recalled
        n_visual_recalled = recall_result.n_visual_recalled

        base_reranker_enabled = self._rerank_cascade.base_enabled_for(route.intent)
        field_reranker_enabled = self._rerank_cascade.field_enabled_for(route.intent)
        base_scores = self._rerank_cascade.base_scores(request.question, candidates, intent=route.intent)

        pairs = list(zip(candidates, base_scores))
        n_before_filter = len(pairs)
        if base_reranker_enabled and self._policy.rerank_score_threshold > 0.0:
            kept = [(candidate, base) for (candidate, base) in pairs if base >= self._policy.rerank_score_threshold]
            pairs = kept or pairs[:1]
        n_filtered = n_before_filter - len(pairs)
        field_rerank_scores = self._rerank_cascade.field_scores(
            request.question,
            [chunk for (chunk, _sem), _base in pairs],
            intent=route.intent,
        )

        scored = []
        for (chunk, _sem), base in pairs:
            retrieved = with_retrieval_scores(
                chunk,
                text_score=base,
                visual_score=None,
                fused_score=base,
                strategy="text",
            )
            scored.append(self._score_child_candidate(
                retrieved,
                request,
                route,
                semantic_score=base,
                field_rerank_score=field_rerank_scores.get(chunk.chunk_id),
            ))
        if visual_hits:
            scored = self._fuse_visual_scores(
                scored,
                visual_hits,
                paper_id=request.paper_id,
                query_text=request.question,
                current_section_index=request.current_section_index,
                intent=route.intent,
                field_rerank_scores=field_rerank_scores,
            )
        scored.sort(key=lambda x: x[1], reverse=True)
        child_chunks = [chunk for chunk, _score in scored[: request.limit]]
        child_chunks = self._structural_expander.expand(child_chunks, request, route)
        supplemental_table_chunks = self._supplemental_table_expander.expand(child_chunks, request, route)
        child_chunks.extend(supplemental_table_chunks)
        top_score = scored[0][1] if scored else 0.0

        parent_chunks, parent_metrics = self._parent_expander.expand(child_chunks, request, route)
        cross_ref_chunks = self._cross_ref_expander.expand(child_chunks, request.paper_id)
        table_context_chunks = self._table_context_expander.expand(child_chunks, request, route)
        ref_chunks = _dedupe_chunks([*cross_ref_chunks, *table_context_chunks])

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        metrics = {
            "retrieval_policy": self._policy.name,
            "retrieval_policy_version": 1,
            "retrieval_policy_config_hash": active_policy_hash,
            "retrieval_policy_overfetch_multiplier": self._policy.overfetch_multiplier,
            "retrieval_policy_element_label_overfetch_multiplier": (
                self._policy.element_label_overfetch_multiplier
            ),
            "candidate_limit": candidate_limit,
            "candidate_filters": candidate_filters,
            "candidate_filter_group_count": len(candidate_filters),
            "hybrid_rrf_enabled": self._policy.hybrid_rrf_enabled,
            "multi_query_enabled": self._policy.multi_query_enabled,
            "sparse_lexical_enabled": self._policy.sparse_lexical_enabled,
            "formula_sparse_enabled": self._policy.formula_sparse_enabled,
            "sparse_recalled": sum(
                1 for chunk, _score in candidates
                if chunk.metadata.get("sparse_lexical_hit")
            ),
            "formula_sparse_recalled": sum(
                1 for chunk, _score in candidates
                if chunk.metadata.get("formula_sparse_hit")
            ),
            "hybrid_rrf_recalled": sum(
                1 for chunk, _score in candidates
                if chunk.metadata.get("hybrid_rrf_fusion")
            ),
            "query_variants": recall_result.query_variants,
            "element_query_labels": sorted(element_query_labels),
            "retrieval_policy_visual_fusion_weights": {
                "text": self._policy.visual_fusion_text_weight,
                "visual": self._policy.visual_fusion_visual_weight,
            },
            "intent": route.intent,
            "recall_routes": list(route.recall_routes),
            "route_plan": plan.route_dict(),
            "retrieval_plan": plan.to_dict(),
            "reranker": self._reranker_available,
            "reranker_enabled_for_intent": base_reranker_enabled,
            "reranker_intent_scope": self._policy.reranking_intents,
            "recalled": n_recalled,
            "visual_recalled": n_visual_recalled,
            "visual_fusion_enabled": self._visual_store_available,
            "field_embedding_enabled": self._field_index_available and self._policy.field_embedding_enabled,
            "field_reranker_enabled": self._field_reranker_available and self._policy.field_reranking_enabled,
            "field_reranker_enabled_for_intent": field_reranker_enabled,
            "field_reranker_intent_scope": self._policy.field_reranking_intents,
            "field_search_fields": self._policy.field_search_fields_for(route.intent),
            "field_hits_count": len(field_hits),
            "field_hits_by_name": _field_hits_by_name(field_hits),
            "claim_index_enabled": self._claim_index_available,
            "claim_index_hits": len(claim_hits),
            "claim_index_top_claim_ids": [hit.record.claim_id for hit in claim_hits[:5]],
            "threshold_filtered": n_filtered,
            "child_returned": len(child_chunks),
            "parent_returned": len(parent_chunks),
            "ref_returned": len(ref_chunks),
            "supplemental_table_returned": len(supplemental_table_chunks),
            "table_context_returned": len(table_context_chunks),
            "figure_context_returned": sum(
                1 for chunk in child_chunks
                if chunk.metadata.get("expansion_reason") in {"figure_nearby_context", "figure_body_reference"}
            ),
            "formula_context_returned": sum(
                1 for chunk in child_chunks
                if chunk.metadata.get("expansion_reason") in _FORMULA_CONTEXT_REASONS
            ) + sum(
                1 for chunk in ref_chunks
                if chunk.metadata.get("expansion_reason") in _FORMULA_CONTEXT_REASONS
            ),
            "interleaved_table_context_returned": sum(
                1 for chunk in child_chunks
                if str(chunk.metadata.get("expansion_reason") or "").startswith("table_")
            ),
            "top_score": round(top_score, 4),
            "elapsed_ms": elapsed_ms,
            "field_scoring_enabled": self._policy.field_scoring_enabled,
            "field_score_weights": self._policy.field_score_weights_for(route.intent),
            "child_score_weights": self._policy.normalized_child_score_weights(),
            "field_scored_count": len(scored),
            "field_score_top": _metadata_extreme(scored, "field_score", max),
            "field_score_min": _metadata_extreme(scored, "field_score", min),
            "field_embedding_score_top": _metadata_extreme(scored, "field_embedding_score", max),
            "field_rerank_top": _metadata_extreme(scored, "field_rerank_score", max),
            "best_matching_fields": _best_matching_fields(scored),
            "retrieval_degradations": [item.to_dict() for item in retrieval_trace.degradations],
            "retrieval_trace": retrieval_trace.to_dict(),
        }
        metrics.update(parent_metrics)
        logging.getLogger(__name__).info("retrieval %s", metrics)
        return self._result_factory(
            parent_chunks=parent_chunks,
            child_chunks=child_chunks,
            ref_chunks=ref_chunks,
            intent=route.intent,
            metadata=metrics,
        )

    def _score_child_candidate(
        self,
        chunk: PaperChunk,
        request: Any,
        route: RetrievalRoute,
        *,
        semantic_score: float,
        field_rerank_score: float | None = None,
    ) -> tuple[PaperChunk, float]:
        return self._child_scorer.score(
            chunk,
            request,
            route,
            semantic_score=semantic_score,
            field_rerank_score=field_rerank_score,
        )

    def _fuse_visual_scores(
        self,
        scored: list[tuple[PaperChunk, float]],
        visual_hits: list[VisualChunkHit],
        *,
        paper_id: str,
        query_text: str,
        current_section_index: int,
        intent: QueryIntent,
        field_rerank_scores: dict[str, float] | None = None,
    ) -> list[tuple[PaperChunk, float]]:
        fused: list[tuple[PaperChunk, float]] = []
        for fused_chunk, fused_score in self._visual_channel.fuse_scores(
            scored,
            visual_hits,
            paper_id=paper_id,
            weights=PaperVisualFusionWeights(
                text=self._policy.visual_fusion_text_weight,
                visual=self._policy.visual_fusion_visual_weight,
            ),
        ):
            fused.append(self._score_child_candidate(
                fused_chunk,
                self._request_factory(
                    paper_id=paper_id,
                    question=query_text,
                    current_section_index=current_section_index,
                ),
                RetrievalRoute(intent=intent),
                semantic_score=fused_score,
                field_rerank_score=(field_rerank_scores or {}).get(fused_chunk.chunk_id),
            ))
        return fused


def _metadata_float(metadata: dict[str, Any], key: str, default: float) -> float:
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _metadata_extreme(
    scored: list[tuple[PaperChunk, float]],
    key: str,
    reducer: Any,
) -> float | None:
    values = [
        _metadata_float(chunk.metadata, key, 0.0)
        for chunk, _score in scored
        if key in chunk.metadata
    ]
    if not values:
        return None
    return round_score(reducer(values))


def _field_hits_by_name(hits: list[FieldEmbeddingHit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.field_name] = counts.get(hit.field_name, 0) + 1
    return counts


def _best_matching_fields(scored: list[tuple[PaperChunk, float]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk, _score in scored:
        field_name = str(chunk.metadata.get("best_matching_field") or "")
        if not field_name:
            continue
        counts[field_name] = counts.get(field_name, 0) + 1
    return counts


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    return dedupe_by_key(chunks, key=lambda chunk: chunk.chunk_id)


__all__ = ["RetrievalPipeline"]
