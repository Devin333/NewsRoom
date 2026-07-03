from __future__ import annotations

import logging
from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.visual_chunk_index import VisualChunkHit, VisualChunkSearchPort
from business.research.rag.retrieval.channels.base import RankedHit, RankedList
from business.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    fuse_visual_retrieval_scores,
    with_retrieval_scores,
)


class VisualRecallChannel:
    name = "visual"

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        visual_store: VisualChunkSearchPort | None,
    ) -> None:
        self._store = chunk_store
        self._visual_store = visual_store

    def recall(
        self,
        request: Any,
        plan: Any,
    ) -> RankedList:
        hits = self.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            candidate_filters=getattr(plan, "candidate_filters", [{}]) or [{}],
            limit=getattr(plan, "limit", 10),
        )
        return [
            RankedHit(
                chunk_id=hit.chunk_id,
                score=hit.score,
                channel=self.name,
                metadata=dict(hit.metadata),
            )
            for hit in hits
        ]

    def search_hits(
        self,
        *,
        paper_id: str,
        query_text: str,
        candidate_filters: list[dict[str, Any]],
        limit: int,
    ) -> list[VisualChunkHit]:
        if self._visual_store is None:
            return []
        hits_by_id: dict[str, VisualChunkHit] = {}
        for filters in candidate_filters:
            try:
                hits = self._visual_store.search_visual_chunks(
                    paper_id,
                    query_text,
                    filters=filters,
                    limit=limit,
                )
            except Exception:
                logging.getLogger(__name__).warning("visual retrieval failed", exc_info=True)
                return []
            for hit in hits:
                existing = hits_by_id.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    hits_by_id[hit.chunk_id] = hit
        hits = list(hits_by_id.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    def fuse_scores(
        self,
        scored: list[tuple[PaperChunk, float]],
        visual_hits: list[VisualChunkHit],
        *,
        paper_id: str,
        weights: PaperVisualFusionWeights,
    ) -> list[tuple[PaperChunk, float]]:
        return fuse_visual_retrieval_scores(
            scored,
            visual_hits,
            paper_id=paper_id,
            chunk_lookup=self._store,
            weights=weights,
        )

    def ranked_chunks(
        self,
        visual_hits: list[VisualChunkHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        out: list[tuple[PaperChunk, float]] = []
        for hit in visual_hits:
            chunk = self._store.get_chunk(hit.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            out.append((
                with_retrieval_scores(
                    chunk,
                    text_score=0.0,
                    visual_score=hit.score,
                    fused_score=hit.score,
                    strategy="visual_channel_rrf",
                ),
                hit.score,
            ))
        out.sort(key=lambda item: item[1], reverse=True)
        return out


__all__ = ["VisualRecallChannel"]
