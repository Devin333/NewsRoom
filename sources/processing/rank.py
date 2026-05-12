from __future__ import annotations

from datetime import UTC, datetime

from domain.sources import NormalizedSourceItem, RankedSourceItem, SourceReliability
from sources.processing.quality import score_source_item


RELIABILITY_SCORE = {
    SourceReliability.HIGH: 1.0,
    SourceReliability.MEDIUM: 0.7,
    SourceReliability.LOW: 0.4,
}


def rank_items(
    items: list[NormalizedSourceItem],
    *,
    topic: str,
    now: datetime | None = None,
) -> list[RankedSourceItem]:
    current_time = now or datetime.now(UTC)
    ranked = [_rank_item(item, topic=topic, now=current_time, index=index) for index, item in enumerate(items)]
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)


def _rank_item(
    item: NormalizedSourceItem,
    *,
    topic: str,
    now: datetime,
    index: int,
) -> RankedSourceItem:
    quality_score = score_source_item(item, now=now)
    relevance = _relevance(item, topic)
    recency = _recency(item, now)
    reliability = RELIABILITY_SCORE[item.source_reliability]
    authority = _authority(item)
    novelty = max(0.5, 1.0 - index * 0.05)
    final_score = round(
        relevance * 0.4 + recency * 0.2 + reliability * 0.2 + authority * 0.1 + novelty * 0.1,
        4,
    )
    ranked_item_id = f"rank_{item.normalized_item_id.removeprefix('norm_')}"
    lineage = dict(item.metadata.get("lineage") or {})
    lineage.update(
        {
            "normalized_item_id": item.normalized_item_id,
            "ranked_item_id": ranked_item_id,
            "relevance_score": round(relevance, 4),
            "recency_score": round(recency, 4),
            "reliability_score": round(reliability, 4),
            "authority_score": round(authority, 4),
            "novelty_score": round(novelty, 4),
            "source_quality_score": quality_score.quality_score,
            "final_score": final_score,
        }
    )
    return RankedSourceItem(
        ranked_item_id=ranked_item_id,
        item=item,
        relevance_score=round(relevance, 4),
        recency_score=round(recency, 4),
        reliability_score=round(reliability, 4),
        novelty_score=round(novelty, 4),
        final_score=final_score,
        rank_reason=(
            f"topic={topic}; relevance={relevance:.2f}; "
            f"reliability={reliability:.2f}; authority={authority:.2f}"
        ),
        metadata={"lineage": lineage, "source_quality": quality_score.to_dict()},
    )


def _relevance(item: NormalizedSourceItem, topic: str) -> float:
    topic_terms = {term for term in topic.casefold().split() if term}
    if not topic_terms:
        return 0.5
    haystack = f"{item.normalized_title} {item.normalized_summary or ''}"
    matches = sum(1 for term in topic_terms if term in haystack)
    return min(1.0, 0.2 + matches / len(topic_terms) * 0.8)


def _recency(item: NormalizedSourceItem, now: datetime) -> float:
    timestamp = item.published_at or item.fetched_at
    age_days = max(0.0, (now - timestamp).total_seconds() / 86400)
    if age_days <= 1:
        return 1.0
    if age_days >= 14:
        return 0.2
    return 1.0 - (age_days - 1) * (0.8 / 13)


def _authority(item: NormalizedSourceItem) -> float:
    try:
        authority = float(item.metadata.get("source_authority_score", 0.5))
    except (TypeError, ValueError):
        authority = 0.5
    return min(1.0, max(0.0, authority))
