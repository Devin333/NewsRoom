from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from business.foundation.models.source import NormalizedSourceItem, SourceItemQualityScore, SourceReliability


RELIABILITY_SCORE = {
    SourceReliability.HIGH: 1.0,
    SourceReliability.MEDIUM: 0.7,
    SourceReliability.LOW: 0.4,
}


def score_source_items(
    items: list[NormalizedSourceItem],
    *,
    now: datetime | None = None,
) -> list[SourceItemQualityScore]:
    current_time = now or datetime.now(UTC)
    return [score_source_item(item, now=current_time) for item in items]


def score_source_item(
    item: NormalizedSourceItem,
    *,
    now: datetime | None = None,
) -> SourceItemQualityScore:
    current_time = now or datetime.now(UTC)
    reliability = RELIABILITY_SCORE[item.source_reliability]
    authority = _authority_score(item)
    traceability = _traceability_score(item)
    freshness = _freshness_score(item, now=current_time)
    content = _content_score(item)
    language = _language_score(item)
    quality_score = round(
        reliability * 0.25
        + authority * 0.20
        + traceability * 0.25
        + freshness * 0.15
        + content * 0.10
        + language * 0.05,
        4,
    )
    return SourceItemQualityScore(
        normalized_item_id=item.normalized_item_id,
        source_item_id=item.source_item_id,
        source_id=item.source_id,
        quality_score=quality_score,
        reliability_score=round(reliability, 4),
        authority_score=round(authority, 4),
        traceability_score=round(traceability, 4),
        freshness_score=round(freshness, 4),
        content_score=round(content, 4),
        language_score=round(language, 4),
        penalties=_penalties(
            item,
            authority_score=authority,
            traceability_score=traceability,
            content_score=content,
            language_score=language,
        ),
        score_reason=(
            "source quality score uses source reliability, authority, traceability, "
            "freshness, content completeness, and language availability"
        ),
    )


def _authority_score(item: NormalizedSourceItem) -> float:
    try:
        value = float(item.metadata.get("source_authority_score", 0.5))
    except (TypeError, ValueError):
        value = 0.5
    return _clamp(value)


def _traceability_score(item: NormalizedSourceItem) -> float:
    lineage = item.metadata.get("lineage") if isinstance(item.metadata.get("lineage"), dict) else {}
    score = 0.0
    if item.source_id and lineage.get("source_id"):
        score += 0.3
    if item.source_item_id and lineage.get("source_item_id"):
        score += 0.3
    if item.canonical_url and lineage.get("canonical_url"):
        score += 0.4
    return round(min(1.0, score), 4)


def _freshness_score(item: NormalizedSourceItem, *, now: datetime) -> float:
    timestamp = item.published_at or item.fetched_at
    age_days = max(0.0, (_as_utc(now) - _as_utc(timestamp)).total_seconds() / 86400)
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.85
    if age_days <= 30:
        return 0.65
    return 0.4


def _content_score(item: NormalizedSourceItem) -> float:
    title = item.normalized_title.strip()
    summary = (item.normalized_summary or "").strip()
    score = 0.0
    if title:
        score += 0.4
    if len(summary) >= 80:
        score += 0.6
    elif len(summary) >= 30:
        score += 0.4
    elif summary:
        score += 0.2
    return round(min(1.0, score), 4)


def _language_score(item: NormalizedSourceItem) -> float:
    language = (item.language or "").strip().casefold()
    if not language or language == "unknown":
        return 0.7
    return 1.0


def _penalties(
    item: NormalizedSourceItem,
    *,
    authority_score: float,
    traceability_score: float,
    content_score: float,
    language_score: float,
) -> list[str]:
    penalties: list[str] = []
    if item.source_reliability == SourceReliability.LOW:
        penalties.append("low_reliability")
    if authority_score < 0.4:
        penalties.append("low_authority")
    if traceability_score < 1.0:
        penalties.append("weak_traceability")
    if content_score < 0.8:
        penalties.append("thin_content")
    if language_score < 1.0:
        penalties.append("language_unknown")
    return penalties


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp(value: Any) -> float:
    return min(1.0, max(0.0, float(value)))
