from __future__ import annotations

from business.memory.models import BusinessMemoryHit


MISRANK_TAGS = {
    "weak_evidence_ranked_too_high",
    "star_spike_overweighted",
    "paper_without_evaluation_overranked",
    "community_noise_overranked",
}


def estimate_previous_misrank_penalty(hits: list[BusinessMemoryHit]) -> float:
    if not hits:
        return 0.0
    penalty = 0.0
    for hit in hits:
        tags = {tag.casefold() for tag in hit.tags}
        metadata_text = " ".join(str(value).casefold() for value in hit.metadata.values() if isinstance(value, str))
        if MISRANK_TAGS & tags:
            penalty += 0.3
        if any(tag in metadata_text for tag in MISRANK_TAGS):
            penalty += 0.2
    return _clamp(penalty)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
