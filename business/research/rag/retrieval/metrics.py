from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.rag.retrieval.scoring import round_score

_FORMULA_CONTEXT_REASONS = frozenset({
    "formula_nearby_context",
    "formula_explained_by",
    "formula_body_reference",
    "formula_explicit_reference",
    "formula_parent_context",
    "formula_reverse_context",
    "formula_reverse_reference",
})


class RetrievalMetricsBuilder:
    def __init__(
        self,
        *,
        policy: Any,
        reranker_available: bool,
        field_index_available: bool,
        field_reranker_available: bool,
        visual_store_available: bool,
        claim_index_available: bool,
    ) -> None:
        self._policy = policy
        self._reranker_available = reranker_available
        self._field_index_available = field_index_available
        self._field_reranker_available = field_reranker_available
        self._visual_store_available = visual_store_available
        self._claim_index_available = claim_index_available

    def build(
        self,
        *,
        active_policy_hash: str,
        plan: Any,
        route: Any,
        candidate_filters: list[dict[str, Any]],
        candidate_limit: int,
        recall_result: Any,
        candidates: list[tuple[PaperChunk, float]],
        field_hits: list[FieldEmbeddingHit],
        claim_hits: list[Any],
        n_recalled: int,
        n_visual_recalled: int,
        base_reranker_enabled: bool,
        field_reranker_enabled: bool,
        n_filtered: int,
        scored: list[tuple[PaperChunk, float]],
        child_chunks: list[PaperChunk],
        parent_chunks: list[PaperChunk],
        ref_chunks: list[PaperChunk],
        supplemental_table_chunks: list[PaperChunk],
        table_context_chunks: list[PaperChunk],
        top_score: float,
        elapsed_ms: float,
        retrieval_trace: Any,
        parent_metrics: dict[str, Any],
    ) -> dict[str, Any]:
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
            "element_query_labels": sorted(set(plan.element_query_labels)),
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
        return metrics


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


__all__ = ["RetrievalMetricsBuilder"]
