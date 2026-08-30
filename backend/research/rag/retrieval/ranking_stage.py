from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.ports.visual_chunk_index import VisualChunkHit
from backend.research.rag.retrieval.paper_policy import RetrievalRoute
from backend.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    with_retrieval_scores,
)
from backend.research.rag.retrieval.scoring import ChildCandidateScorer


@dataclass(frozen=True)
class ChildRankingResult:
    scored: list[tuple[PaperChunk, float]]
    child_chunks: list[PaperChunk]
    base_reranker_enabled: bool
    field_reranker_enabled: bool
    n_filtered: int
    field_rerank_scores: dict[str, float]


class ChildRankingStage:
    def __init__(
        self,
        *,
        policy: Any,
        rerank_cascade: Any,
        child_scorer: ChildCandidateScorer,
        visual_channel: Any,
        request_factory: Callable[..., Any],
    ) -> None:
        self._policy = policy
        self._rerank_cascade = rerank_cascade
        self._child_scorer = child_scorer
        self._visual_channel = visual_channel
        self._request_factory = request_factory

    def rank(
        self,
        request: Any,
        route: RetrievalRoute,
        candidates: list[tuple[PaperChunk, float]],
        visual_hits: list[VisualChunkHit],
        *,
        limit: int,
    ) -> ChildRankingResult:
        base_reranker_enabled = self._rerank_cascade.base_enabled_for(route.intent)
        field_reranker_enabled = self._rerank_cascade.field_enabled_for(route.intent)
        base_scores = self._rerank_cascade.base_scores(
            request.question,
            candidates,
            intent=route.intent,
        )

        pairs = list(zip(candidates, base_scores))
        n_before_filter = len(pairs)
        if base_reranker_enabled and self._policy.rerank_score_threshold > 0.0:
            kept = [
                (candidate, base)
                for (candidate, base) in pairs
                if base >= self._policy.rerank_score_threshold
            ]
            pairs = kept or pairs[:1]
        n_filtered = n_before_filter - len(pairs)

        field_rerank_scores = self._rerank_cascade.field_scores(
            request.question,
            [chunk for (chunk, _sem), _base in pairs],
            intent=route.intent,
        )

        scored: list[tuple[PaperChunk, float]] = []
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

        scored.sort(key=lambda item: item[1], reverse=True)
        return ChildRankingResult(
            scored=scored,
            child_chunks=[chunk for chunk, _score in scored[:limit]],
            base_reranker_enabled=base_reranker_enabled,
            field_reranker_enabled=field_reranker_enabled,
            n_filtered=n_filtered,
            field_rerank_scores=field_rerank_scores,
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
        intent: str,
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


__all__ = ["ChildRankingResult", "ChildRankingStage"]
