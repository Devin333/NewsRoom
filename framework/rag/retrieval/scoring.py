from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from framework.rag.core import RAGEvidence, RAGScoreBreakdown


@dataclass(frozen=True)
class RAGScoringWeights:
    child_similarity: float = 0.50
    parent_relevance: float = 0.25
    field_score: float = 0.15
    section_heading_score: float = 0.07
    position_bonus: float = 0.03
    rerank_score: float = 0.0
    normalize_present_components: bool = True

    def as_component_weights(self) -> dict[str, float]:
        return {
            "child_similarity": self.child_similarity,
            "parent_relevance": self.parent_relevance,
            "field_score": self.field_score,
            "section_heading_score": self.section_heading_score,
            "position_bonus": self.position_bonus,
            "rerank_score": self.rerank_score,
        }


def fuse_score(
    breakdown: RAGScoreBreakdown,
    *,
    weights: RAGScoringWeights | None = None,
    fallback_score: float = 0.0,
) -> float:
    resolved_weights = weights or RAGScoringWeights()
    weighted_sum = 0.0
    used_weight = 0.0
    for component, weight in resolved_weights.as_component_weights().items():
        if weight == 0:
            continue
        value = getattr(breakdown, component)
        if value is None:
            continue
        weighted_sum += value * weight
        used_weight += weight
    if used_weight > 0:
        if resolved_weights.normalize_present_components:
            return weighted_sum / used_weight
        return weighted_sum
    if breakdown.final_score is not None:
        return breakdown.final_score
    return float(fallback_score)


def score_evidence(evidence: RAGEvidence, *, weights: RAGScoringWeights | None = None) -> RAGEvidence:
    final_score = fuse_score(evidence.score_breakdown, weights=weights, fallback_score=evidence.score)
    breakdown = replace(evidence.score_breakdown, final_score=final_score)
    metadata: dict[str, Any] = dict(evidence.metadata)
    metadata["rag_score_weights"] = (weights or RAGScoringWeights()).as_component_weights()
    metadata["rag_score_normalized"] = (weights or RAGScoringWeights()).normalize_present_components
    return replace(evidence, score=final_score, score_breakdown=breakdown, metadata=metadata)


def normalize_score_weights(
    weights: Mapping[str, float],
    *,
    keys: tuple[str, ...],
    fallback: Mapping[str, float],
) -> dict[str, float]:
    normalized = {key: max(0.0, float(weights.get(key, 0.0))) for key in keys}
    total = sum(normalized.values())
    if total <= 0.0:
        return dict(fallback)
    return {key: round(value / total, 6) for key, value in normalized.items()}


def weighted_component_score(
    components: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> float:
    total = 0.0
    for name, weight in weights.items():
        value = components.get(name)
        if value is None:
            continue
        total += float(value) * float(weight)
    return total


__all__ = [
    "RAGScoringWeights",
    "fuse_score",
    "normalize_score_weights",
    "score_evidence",
    "weighted_component_score",
]
