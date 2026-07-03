from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from framework.rag.retrieval import dedupe_by_key

from business.research.document.models import PaperChunk
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval.metrics import RetrievalMetricsBuilder
from business.research.rag.retrieval.paper_policy import QueryIntent, RetrievalRoute
from business.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    with_retrieval_scores,
)
from business.research.rag.retrieval.policy_config import policy_config_hash
from business.research.rag.retrieval.scoring import ChildCandidateScorer
from business.research.rag.retrieval.trace import RetrievalTrace


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
        self._metrics_builder = RetrievalMetricsBuilder(
            policy=policy,
            reranker_available=reranker_available,
            field_index_available=field_index_available,
            field_reranker_available=field_reranker_available,
            visual_store_available=visual_store_available,
            claim_index_available=claim_index_available,
        )

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
        metrics = self._metrics_builder.build(
            active_policy_hash=active_policy_hash,
            plan=plan,
            route=route,
            candidate_filters=candidate_filters,
            candidate_limit=candidate_limit,
            recall_result=recall_result,
            candidates=candidates,
            field_hits=field_hits,
            claim_hits=claim_hits,
            n_recalled=n_recalled,
            n_visual_recalled=n_visual_recalled,
            base_reranker_enabled=base_reranker_enabled,
            field_reranker_enabled=field_reranker_enabled,
            n_filtered=n_filtered,
            scored=scored,
            child_chunks=child_chunks,
            parent_chunks=parent_chunks,
            ref_chunks=ref_chunks,
            supplemental_table_chunks=supplemental_table_chunks,
            table_context_chunks=table_context_chunks,
            top_score=top_score,
            elapsed_ms=elapsed_ms,
            retrieval_trace=retrieval_trace,
            parent_metrics=parent_metrics,
        )
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


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    return dedupe_by_key(chunks, key=lambda chunk: chunk.chunk_id)


__all__ = ["RetrievalPipeline"]
