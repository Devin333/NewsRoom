from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from business.research.document.models import PaperChunk
from business.research.ports.visual_chunk_index import VisualChunkHit


class PaperChunkLookup(Protocol):
    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        ...


@dataclass(frozen=True)
class PaperVisualFusionWeights:
    text: float
    visual: float


def fuse_visual_retrieval_scores(
    scored: list[tuple[PaperChunk, float]],
    visual_hits: list[VisualChunkHit],
    *,
    paper_id: str,
    chunk_lookup: PaperChunkLookup,
    weights: PaperVisualFusionWeights,
) -> list[tuple[PaperChunk, float]]:
    by_id: dict[str, tuple[PaperChunk, float, float | None]] = {}
    for chunk, score in scored:
        by_id[chunk.chunk_id] = (
            chunk,
            _metadata_float(chunk.metadata, "text_score", score),
            None,
        )

    for hit in visual_hits:
        existing = by_id.get(hit.chunk_id)
        chunk = existing[0] if existing else None
        if chunk is None:
            chunk = chunk_lookup.get_chunk(hit.chunk_id)
        if chunk is None or chunk.paper_id != paper_id:
            continue
        text_score = existing[1] if existing else 0.0
        by_id[chunk.chunk_id] = (chunk, text_score, hit.score)

    fused: list[tuple[PaperChunk, float]] = []
    for chunk, text_score, visual_score in by_id.values():
        fused_score, strategy = visual_fusion_score(
            text_score=text_score,
            visual_score=visual_score,
            weights=weights,
        )
        fused.append((
            with_retrieval_scores(
                chunk,
                text_score=text_score,
                visual_score=visual_score,
                fused_score=fused_score,
                strategy=strategy,
            ),
            fused_score,
        ))
    return fused


def visual_fusion_score(
    *,
    text_score: float,
    visual_score: float | None,
    weights: PaperVisualFusionWeights,
) -> tuple[float, str]:
    text = max(0.0, text_score)
    if visual_score is None:
        return text_score, "text"
    visual = max(0.0, visual_score)
    if text:
        score = weights.text * text + weights.visual * visual
        return score, "text_image_fusion"
    return visual * weights.visual, "image_only"


def with_retrieval_scores(
    chunk: PaperChunk,
    *,
    text_score: float,
    visual_score: float | None,
    fused_score: float,
    strategy: str,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata["text_score"] = round(float(text_score), 6)
    metadata["fused_score"] = round(float(fused_score), 6)
    metadata["fusion_strategy"] = strategy
    metadata["visual_hit"] = visual_score is not None
    if visual_score is not None:
        metadata["visual_score"] = round(float(visual_score), 6)
    return chunk.model_copy(update={"metadata": metadata})


def _metadata_float(metadata: dict[str, object], key: str, default: float) -> float:
    value = metadata.get(key)
    if isinstance(value, bool):
        return default
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


__all__ = [
    "PaperVisualFusionWeights",
    "fuse_visual_retrieval_scores",
    "visual_fusion_score",
    "with_retrieval_scores",
]
