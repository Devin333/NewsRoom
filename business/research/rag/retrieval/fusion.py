from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.channels.base import RankedHit, RankedList


def fuse_ranked_hits(
    rankings: list[tuple[str, RankedList]],
    *,
    limit: int,
    rrf_k: int,
) -> list[RankedHit]:
    if not rankings:
        return []
    by_id: dict[str, dict[str, Any]] = {}
    channel_count = 0
    for channel_name, ranked_items in rankings:
        if not ranked_items:
            continue
        channel_count += 1
        seen_in_channel: set[str] = set()
        for rank, hit in enumerate(ranked_items, start=1):
            if hit.chunk_id in seen_in_channel:
                continue
            seen_in_channel.add(hit.chunk_id)
            entry = by_id.setdefault(hit.chunk_id, {
                "chunk_id": hit.chunk_id,
                "metadata": {},
                "contributions": {},
                "channel_scores": {},
                "total": 0.0,
            })
            entry["metadata"].update(hit.metadata)
            contribution = 1.0 / (max(1, rrf_k) + rank)
            entry["contributions"][channel_name] = contribution
            entry["channel_scores"][channel_name] = _round_score(hit.score)
            entry["total"] += contribution
    if not by_id:
        return []
    max_total = max(1.0 / (max(1, rrf_k) + 1) * max(1, channel_count), 1e-9)
    fused: list[RankedHit] = []
    for entry in by_id.values():
        normalized_score = _clamp_score(float(entry["total"]) / max_total)
        metadata = dict(entry["metadata"])
        metadata["rrf_contributions"] = {
            channel: _round_score(score)
            for channel, score in sorted(entry["contributions"].items())
        }
        metadata["rrf_channel_scores"] = {
            channel: _round_score(score)
            for channel, score in sorted(entry["channel_scores"].items())
        }
        fused.append(RankedHit(
            chunk_id=str(entry["chunk_id"]),
            score=_round_score(normalized_score),
            channel="rrf",
            metadata=metadata,
        ))
    fused.sort(key=lambda item: (-item.score, item.chunk_id))
    return fused[:limit]


def fuse_chunk_rankings(
    rankings: list[tuple[str, list[tuple[PaperChunk, float]]]],
    *,
    limit: int,
    rrf_k: int,
    metadata_prefix: str,
) -> list[tuple[PaperChunk, float]]:
    if not rankings:
        return []
    by_id: dict[str, dict[str, Any]] = {}
    channel_count = 0
    for channel_name, ranked_items in rankings:
        if not ranked_items:
            continue
        channel_count += 1
        seen_in_channel: set[str] = set()
        for rank, (chunk, raw_score) in enumerate(ranked_items, start=1):
            if chunk.chunk_id in seen_in_channel:
                continue
            seen_in_channel.add(chunk.chunk_id)
            entry = by_id.setdefault(chunk.chunk_id, {
                "chunk": chunk,
                "contributions": {},
                "channel_scores": {},
                "total": 0.0,
            })
            entry["chunk"] = _merge_chunk_metadata(entry["chunk"], chunk)
            contribution = 1.0 / (max(1, rrf_k) + rank)
            entry["contributions"][channel_name] = contribution
            entry["channel_scores"][channel_name] = _round_score(raw_score)
            entry["total"] += contribution
    if not by_id:
        return []
    max_total = max(1.0 / (max(1, rrf_k) + 1) * max(1, channel_count), 1e-9)
    fused: list[tuple[PaperChunk, float]] = []
    for entry in by_id.values():
        normalized_score = _clamp_score(float(entry["total"]) / max_total)
        chunk = entry["chunk"]
        metadata = dict(chunk.metadata)
        contributions = {
            channel: _round_score(score)
            for channel, score in sorted(entry["contributions"].items())
        }
        channel_scores = {
            channel: _round_score(score)
            for channel, score in sorted(entry["channel_scores"].items())
        }
        metadata.update({
            f"{metadata_prefix}_rrf_score": _round_score(normalized_score),
            f"{metadata_prefix}_rrf_channels": sorted(contributions),
            f"{metadata_prefix}_rrf_channel_contributions": contributions,
            f"{metadata_prefix}_channel_scores": channel_scores,
        })
        if metadata_prefix == "hybrid":
            metadata.update({
                "hybrid_rrf_fusion": True,
                "rrf_score": _round_score(normalized_score),
                "rrf_channels": sorted(contributions),
                "rrf_channel_contributions": contributions,
            })
        else:
            metadata[f"{metadata_prefix}_rrf_fusion"] = True
            if metadata_prefix == "text":
                metadata.update({
                    "hybrid_rrf_fusion": True,
                    "rrf_score": _round_score(normalized_score),
                    "rrf_channels": sorted(contributions),
                    "rrf_channel_contributions": contributions,
                })
        fused.append((chunk.model_copy(update={"metadata": metadata}), _round_score(normalized_score)))
    fused.sort(key=lambda item: (-item[1], item[0].section_index, item[0].chunk_id))
    return fused[:limit]


def _merge_chunk_metadata(base: PaperChunk, incoming: PaperChunk) -> PaperChunk:
    if base.chunk_id != incoming.chunk_id:
        return base
    metadata = dict(base.metadata)
    metadata.update(incoming.metadata)
    return base.model_copy(update={"metadata": metadata})


def _round_score(value: float) -> float:
    return round(float(value), 6)


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = ["fuse_chunk_rankings", "fuse_ranked_hits"]
