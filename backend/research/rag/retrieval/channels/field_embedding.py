from __future__ import annotations

import logging
from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.ports.chunk_store import ChunkStorePort
from backend.research.ports.field_embedding_index import FieldEmbeddingHit, FieldEmbeddingSearchPort
from backend.research.rag.adapters.paper_field_text import FIELD_NAMES
from backend.research.rag.retrieval.channels.base import RankedHit, RankedList


class FieldEmbeddingChannel:
    name = "field_embedding"

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        field_index: FieldEmbeddingSearchPort | None,
    ) -> None:
        self._store = chunk_store
        self._field_index = field_index

    def recall(
        self,
        request: Any,
        plan: Any,
    ) -> RankedList:
        hits = self.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            field_names=getattr(plan, "field_names", None),
            candidate_filters=getattr(plan, "candidate_filters", [{}]) or [{}],
            limit=getattr(plan, "limit", 10),
        )
        return [
            RankedHit(
                chunk_id=hit.chunk_id,
                score=hit.score,
                channel=self.name,
                metadata=_field_hit_metadata(hit),
            )
            for hit in hits
        ]

    def search_hits(
        self,
        *,
        paper_id: str,
        query_text: str,
        field_names: tuple[str, ...] | None,
        candidate_filters: list[dict[str, Any]],
        limit: int,
    ) -> list[FieldEmbeddingHit]:
        if self._field_index is None:
            return []
        hits_by_key: dict[tuple[str, str], FieldEmbeddingHit] = {}
        for filters in candidate_filters:
            try:
                hits = self._field_index.search_field_vectors(
                    paper_id,
                    query_text,
                    field_names=field_names,
                    filters=filters,
                    limit=limit,
                )
            except Exception:
                logging.getLogger(__name__).warning("field embedding retrieval failed", exc_info=True)
                return []
            for hit in hits:
                key = (hit.chunk_id, hit.field_name)
                existing = hits_by_key.get(key)
                if existing is None or hit.score > existing.score:
                    hits_by_key[key] = hit
        hits = list(hits_by_key.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    def merge_hits(
        self,
        candidates: list[tuple[PaperChunk, float]],
        field_hits: list[FieldEmbeddingHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        if not field_hits:
            return candidates
        by_id: dict[str, tuple[PaperChunk, float]] = {
            chunk.chunk_id: (chunk, score)
            for chunk, score in candidates
        }
        for hit in field_hits:
            existing = by_id.get(hit.chunk_id)
            chunk = existing[0] if existing else self._store.get_chunk(hit.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            metadata = merge_field_embedding_hit(chunk.metadata, hit)
            merged_chunk = chunk.model_copy(update={"metadata": metadata})
            by_id[merged_chunk.chunk_id] = (merged_chunk, existing[1] if existing else 0.0)
        return list(by_id.values())

    def ranked_chunks(
        self,
        field_hits: list[FieldEmbeddingHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        by_id: dict[str, tuple[PaperChunk, float]] = {}
        for hit in field_hits:
            existing = by_id.get(hit.chunk_id)
            chunk = existing[0] if existing else self._store.get_chunk(hit.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            metadata = merge_field_embedding_hit(chunk.metadata, hit)
            merged = chunk.model_copy(update={"metadata": metadata})
            if existing is None or hit.score > existing[1]:
                by_id[hit.chunk_id] = (merged, hit.score)
        ranked = list(by_id.values())
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked


def merge_field_embedding_hit(
    metadata: dict[str, Any],
    hit: FieldEmbeddingHit,
) -> dict[str, Any]:
    out = dict(metadata)
    field_name = str(hit.field_name).casefold()
    if field_name not in FIELD_NAMES:
        return out

    raw_scores = out.get("field_embedding_scores")
    scores = {
        str(key): clamp_score(float(value))
        for key, value in (raw_scores.items() if isinstance(raw_scores, dict) else [])
        if str(key) in FIELD_NAMES
    }
    scores[field_name] = max(scores.get(field_name, 0.0), clamp_score(hit.score))

    raw_hits = out.get("field_embedding_hits")
    hit_records = [
        dict(item)
        for item in raw_hits
        if isinstance(raw_hits, list) and isinstance(item, dict)
    ] if isinstance(raw_hits, list) else []
    hit_records.append(_field_hit_record(hit, field_name))
    hit_records.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)

    best_field, best_score = _best_score_item(scores)
    out["field_embedding_scores"] = {name: round_score(score) for name, score in scores.items()}
    for name in FIELD_NAMES:
        out[f"{name}_embedding_score"] = round_score(scores.get(name, 0.0))
    out["field_embedding_score"] = round_score(best_score)
    out["best_embedding_field"] = best_field
    out["field_embedding_hits"] = hit_records[:8]
    out["field_embedding_hit_count"] = len(hit_records)
    return out


def _field_hit_metadata(hit: FieldEmbeddingHit) -> dict[str, Any]:
    return {
        "field_name": str(hit.field_name).casefold(),
        "field_score": round_score(clamp_score(hit.score)),
        "field_text_preview": " ".join(hit.field_text.split())[:240],
        "source_locator": hit.metadata.get("source_locator", ""),
        "caption_source_locator": hit.metadata.get("caption_source_locator", ""),
    }


def _field_hit_record(hit: FieldEmbeddingHit, field_name: str) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "score": round_score(clamp_score(hit.score)),
        "field_text_preview": " ".join(hit.field_text.split())[:240],
        "source_locator": hit.metadata.get("source_locator", ""),
        "caption_source_locator": hit.metadata.get("caption_source_locator", ""),
    }


def _best_score_item(scores: dict[str, float]) -> tuple[str, float]:
    if not scores:
        return "", 0.0
    field_name, score = max(scores.items(), key=lambda item: (item[1], -FIELD_NAMES.index(item[0])))
    if score <= 0.0:
        return "", 0.0
    return field_name, clamp_score(score)


def clamp_score(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def round_score(value: float) -> float:
    return round(float(value), 6)


__all__ = ["FieldEmbeddingChannel", "merge_field_embedding_hit"]
