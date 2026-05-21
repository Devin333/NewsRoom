from __future__ import annotations

from business.memory.models import BusinessMemoryHit


def estimate_source_reliability(
    hits: list[BusinessMemoryHit],
    *,
    source_name: str | None = None,
) -> float:
    if not hits:
        return 0.5
    matching = [
        hit for hit in hits
        if source_name is None or (hit.source_name or "").casefold() == source_name.casefold()
    ] or hits
    positive = 0.0
    negative = 0.0
    for hit in matching:
        tags = {tag.casefold() for tag in hit.tags}
        metadata_text = " ".join(str(value).casefold() for value in hit.metadata.values() if isinstance(value, str))
        confidence = _metadata_score(hit, "confidence", default=hit.score)
        if confidence >= 0.75 or {"high_confidence", "reliable_source", "verified_evidence"} & tags:
            positive += 1.0
        if "high confidence" in metadata_text or "verified" in metadata_text:
            positive += 0.5
        if {"repeated_noise", "weak_evidence", "unreliable_source"} & tags:
            negative += 1.0
        if "noise" in metadata_text or "weak evidence" in metadata_text:
            negative += 0.5
    return _clamp(0.5 + positive * 0.12 - negative * 0.15)


def source_noise_penalty(hits: list[BusinessMemoryHit]) -> float:
    if not hits:
        return 0.0
    noisy = 0.0
    for hit in hits:
        tags = {tag.casefold() for tag in hit.tags}
        metadata_text = " ".join(str(value).casefold() for value in hit.metadata.values() if isinstance(value, str))
        if {"repeated_noise", "weak_evidence", "low_quality_source"} & tags:
            noisy += 1.0
        if "noise" in metadata_text or "low quality" in metadata_text:
            noisy += 0.5
    return _clamp(noisy / max(1.0, len(hits)))


def _metadata_score(hit: BusinessMemoryHit, key: str, *, default: float = 0.0) -> float:
    value = hit.metadata.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
