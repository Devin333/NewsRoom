from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc

from business.foundation.models.source import NormalizedSourceItem, RankedSourceItem, SourceReliability
from business.layers.signal.source_processing.quality import score_source_item


RELIABILITY_SCORE = {
    SourceReliability.HIGH: 1.0,
    SourceReliability.MEDIUM: 0.7,
    SourceReliability.LOW: 0.4,
}


def rank_items(
    items: list[NormalizedSourceItem],
    *,
    topic: str,
    subscription_topics: list[str] | None = None,
    now: datetime | None = None,
) -> list[RankedSourceItem]:
    current_time = now or datetime.now(UTC)
    ranked = [
        _rank_item(
            item,
            topic=topic,
            subscription_topics=subscription_topics or [topic],
            now=current_time,
            index=index,
        )
        for index, item in enumerate(items)
    ]
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)


def _rank_item(
    item: NormalizedSourceItem,
    *,
    topic: str,
    subscription_topics: list[str],
    now: datetime,
    index: int,
) -> RankedSourceItem:
    quality_score = score_source_item(item, now=now)
    relevance = _relevance(item, topic)
    recency = _recency(item, now)
    reliability = RELIABILITY_SCORE[item.source_reliability]
    authority = _authority(item)
    duplicate_cluster = _duplicate_cluster_score(item)
    historical_importance = _historical_importance(item)
    subscription_match = _subscription_match(item, subscription_topics)
    novelty = max(0.5, 1.0 - index * 0.05)
    final_score = round(
        relevance * 0.28
        + recency * 0.14
        + reliability * 0.14
        + authority * 0.12
        + novelty * 0.08
        + duplicate_cluster * 0.08
        + historical_importance * 0.08
        + subscription_match * 0.08,
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
            "duplicate_cluster_score": round(duplicate_cluster, 4),
            "historical_importance_score": round(historical_importance, 4),
            "subscription_match_score": round(subscription_match, 4),
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
        authority_score=round(authority, 4),
        duplicate_cluster_score=round(duplicate_cluster, 4),
        historical_importance_score=round(historical_importance, 4),
        subscription_match_score=round(subscription_match, 4),
        source_quality_score=quality_score.quality_score,
        rank_reason=(
            f"topic={topic}; relevance={relevance:.2f}; "
            f"reliability={reliability:.2f}; authority={authority:.2f}; "
            f"cluster={duplicate_cluster:.2f}; historical={historical_importance:.2f}; "
            f"subscription={subscription_match:.2f}"
        ),
        lineage=lineage_from_item(item, ranked_item_id=ranked_item_id),
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


def _duplicate_cluster_score(item: NormalizedSourceItem) -> float:
    cluster = item.metadata.get("duplicate_cluster")
    if not isinstance(cluster, dict):
        return 0.5
    try:
        cluster_size = int(cluster.get("cluster_size") or 1)
    except (TypeError, ValueError):
        cluster_size = 1
    if cluster_size <= 1:
        return 0.5
    if bool(cluster.get("same_event_cluster")):
        return min(1.0, 0.55 + min(cluster_size, 6) * 0.075)
    return min(1.0, 0.5 + min(cluster_size, 5) * 0.08)


def _historical_importance(item: NormalizedSourceItem) -> float:
    for key in (
        "historical_importance_score",
        "historical_accuracy_score",
        "source_historical_importance",
    ):
        if key in item.metadata:
            try:
                return min(1.0, max(0.0, float(item.metadata[key])))
            except (TypeError, ValueError):
                return 0.5
    return 0.5


def _subscription_match(item: NormalizedSourceItem, subscription_topics: list[str]) -> float:
    terms = {
        term
        for topic in subscription_topics
        for term in str(topic).casefold().replace("-", " ").replace("_", " ").split()
        if term
    }
    if not terms:
        return 0.5
    haystack = f"{item.normalized_title} {item.normalized_summary or ''} {' '.join(_item_tags(item))}"
    matches = sum(1 for term in terms if term in haystack)
    return min(1.0, matches / len(terms)) if matches else 0.0


def _item_tags(item: NormalizedSourceItem) -> list[str]:
    tags = item.metadata.get("tags") or item.metadata.get("source_tags") or []
    if not isinstance(tags, list):
        return []
    return [str(tag).casefold() for tag in tags]


def lineage_from_item(item: NormalizedSourceItem, *, ranked_item_id: str):
    from business.foundation.models.source import Lineage

    lineage = item.lineage
    return Lineage(
        source_id=item.source_id,
        source_item_id=item.source_item_id,
        normalized_item_id=item.normalized_item_id,
        ranked_item_id=ranked_item_id,
        raw_url=item.url,
        canonical_url=item.canonical_url,
        fetched_at=item.fetched_at,
        published_at=item.published_at,
        raw_artifact_ref=(lineage.raw_artifact_ref if lineage else None),
        parse_artifact_ref=(lineage.parse_artifact_ref if lineage else None),
    )
