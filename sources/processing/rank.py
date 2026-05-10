from __future__ import annotations

from datetime import UTC, datetime

from domain.sources import NormalizedSourceItem, RankedSourceItem, SourceReliability


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
    relevance = _relevance(item, topic)
    recency = _recency(item, now)
    reliability = RELIABILITY_SCORE[item.source_reliability]
    novelty = max(0.5, 1.0 - index * 0.05)
    final_score = round(
        relevance * 0.45 + recency * 0.2 + reliability * 0.25 + novelty * 0.1,
        4,
    )
    return RankedSourceItem(
        ranked_item_id=f"rank_{item.normalized_item_id.removeprefix('norm_')}",
        item=item,
        relevance_score=round(relevance, 4),
        recency_score=round(recency, 4),
        reliability_score=round(reliability, 4),
        novelty_score=round(novelty, 4),
        final_score=final_score,
        rank_reason=f"topic={topic}; relevance={relevance:.2f}; reliability={reliability:.2f}",
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
