from __future__ import annotations

import logging
from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.ports.chunk_store import ChunkStorePort
from backend.research.rag.retrieval.channels.base import RankedHit, RankedList
from backend.research.rag.retrieval.paper_claim_index import ClaimSearchHit, PaperClaimSearchPort


class ClaimIndexChannel:
    name = "claim_index"

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        claim_index: PaperClaimSearchPort | None,
    ) -> None:
        self._store = chunk_store
        self._claim_index = claim_index

    def recall(
        self,
        request: Any,
        plan: Any,
    ) -> RankedList:
        hits = self.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            limit=getattr(plan, "limit", 10),
        )
        return [
            RankedHit(
                chunk_id=hit.record.chunk_id,
                score=hit.score,
                channel=self.name,
                metadata=_claim_hit_metadata(hit),
            )
            for hit in hits
        ]

    def search_hits(
        self,
        *,
        paper_id: str,
        query_text: str,
        limit: int,
    ) -> list[ClaimSearchHit]:
        if self._claim_index is None:
            return []
        try:
            return self._claim_index.search_claims(
                paper_id,
                query_text,
                limit=limit,
            )
        except Exception:
            logging.getLogger(__name__).warning("claim index retrieval failed", exc_info=True)
            return []

    def merge_hits(
        self,
        candidates: list[tuple[PaperChunk, float]],
        claim_hits: list[ClaimSearchHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        if not claim_hits:
            return candidates
        by_id: dict[str, tuple[PaperChunk, float]] = {
            chunk.chunk_id: (chunk, score)
            for chunk, score in candidates
        }
        for hit in claim_hits:
            record = hit.record
            if record.paper_id != paper_id:
                continue
            existing = by_id.get(record.chunk_id)
            chunk = existing[0] if existing else self._store.get_chunk(record.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            merged_chunk = merge_claim_index_hit(chunk, hit)
            by_id[merged_chunk.chunk_id] = (
                merged_chunk,
                max(existing[1] if existing else 0.0, hit.score),
            )
        return list(by_id.values())

    def ranked_chunks(
        self,
        claim_hits: list[ClaimSearchHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        out: list[tuple[PaperChunk, float]] = []
        for hit in claim_hits:
            record = hit.record
            if record.paper_id != paper_id:
                continue
            chunk = self._store.get_chunk(record.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            out.append((merge_claim_index_hit(chunk, hit), hit.score))
        out.sort(key=lambda item: item[1], reverse=True)
        return out


def merge_claim_index_hit(chunk: PaperChunk, hit: ClaimSearchHit) -> PaperChunk:
    metadata = dict(chunk.metadata)
    existing_score = _metadata_float(metadata, "claim_index_score", 0.0)
    if existing_score > hit.score:
        return chunk
    metadata.update(_claim_hit_metadata(hit))
    return chunk.model_copy(update={"metadata": metadata})


def _claim_hit_metadata(hit: ClaimSearchHit) -> dict[str, Any]:
    record = hit.record
    return {
        "claim_index_hit": True,
        "claim_index_score": round_score(hit.score),
        "claim_id": record.claim_id,
        "claim_text": record.claim_text,
        "claim_type": record.claim_type,
        "claim_source_locator": record.source_locator,
        "claim_section_title": record.section_title,
    }


def _metadata_float(metadata: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
    return value


def round_score(value: float) -> float:
    return round(float(value), 6)


__all__ = ["ClaimIndexChannel", "merge_claim_index_hit"]
