from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha256

from business.foundation.models.source import (
    DedupResult,
    DuplicateGroup,
    NormalizedSourceItem,
    SourceDuplicateCluster,
    SourceRankingSignals,
    SourceReliability,
)


RELIABILITY_PRIORITY = {
    SourceReliability.HIGH: 3,
    SourceReliability.MEDIUM: 2,
    SourceReliability.LOW: 1,
}
NEAR_DUPLICATE_TITLE_THRESHOLD = 0.8
NEAR_DUPLICATE_MIN_TITLE_TERMS = 4
TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "new",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def deduplicate_items(items: list[NormalizedSourceItem]) -> list[NormalizedSourceItem]:
    return deduplicate_with_result(items).kept_items


def deduplicate_with_result(items: list[NormalizedSourceItem]) -> DedupResult:
    groups: list[list[NormalizedSourceItem]] = []
    for item in items:
        matching_indexes = [
            index
            for index, group in enumerate(groups)
            if any(_is_duplicate(item, existing) for existing in group)
        ]
        if not matching_indexes:
            groups.append([item])
            continue

        target_index = matching_indexes[0]
        groups[target_index].append(item)
        for merge_index in reversed(matching_indexes[1:]):
            groups[target_index].extend(groups[merge_index])
            del groups[merge_index]

    kept_items: list[NormalizedSourceItem] = []
    dropped_items: list[NormalizedSourceItem] = []
    duplicate_groups: list[DuplicateGroup] = []
    for group in groups:
        original_kept_item = max(group, key=_retention_priority)
        dropped = [item for item in group if item is not original_kept_item]
        kept_item = _with_duplicate_cluster_metadata(original_kept_item, group, dropped)
        kept_items.append(kept_item)
        if len(group) <= 1:
            continue
        dropped_items.extend(dropped)
        duplicate_groups.append(_duplicate_group(group, kept_item, dropped))
    return DedupResult(
        kept_items=kept_items,
        duplicate_groups=duplicate_groups,
        dropped_items=dropped_items,
        metadata={
            "input_count": len(items),
            "kept_count": len(kept_items),
            "dropped_count": len(dropped_items),
        },
    )


def _is_duplicate(left: NormalizedSourceItem, right: NormalizedSourceItem) -> bool:
    return bool(_duplicate_reasons(left, right))


def _duplicate_reasons(left: NormalizedSourceItem, right: NormalizedSourceItem) -> list[str]:
    reasons = []
    if left.canonical_url_hash == right.canonical_url_hash:
        reasons.append("canonical_url_hash")
    if left.title_hash == right.title_hash:
        reasons.append("title_hash")
    if left.content_hash == right.content_hash:
        reasons.append("content_hash")
    if _near_duplicate_title(left.normalized_title, right.normalized_title):
        reasons.append("near_duplicate_title")
    return reasons


def _duplicate_group(
    group: list[NormalizedSourceItem],
    kept_item: NormalizedSourceItem,
    dropped_items: list[NormalizedSourceItem],
) -> DuplicateGroup:
    item_ids = sorted(item.normalized_item_id for item in group)
    reasons = sorted(
        {
            reason
            for index, left in enumerate(group)
            for right in group[index + 1 :]
            for reason in _duplicate_reasons(left, right)
        }
    )
    canonical_urls = sorted({item.canonical_url for item in group if item.canonical_url})
    return DuplicateGroup(
        group_id=f"dup_{sha256('|'.join(item_ids).encode('utf-8')).hexdigest()[:16]}",
        kept_item_id=kept_item.normalized_item_id,
        duplicate_item_ids=[item.normalized_item_id for item in dropped_items],
        reasons=reasons,
        canonical_urls=canonical_urls,
        metadata={
            "group_size": len(group),
            "source_item_ids": [item.source_item_id for item in group],
            "dropped_source_item_ids": [item.source_item_id for item in dropped_items],
        },
    )


def _with_duplicate_cluster_metadata(
    kept_item: NormalizedSourceItem,
    group: list[NormalizedSourceItem],
    dropped_items: list[NormalizedSourceItem],
) -> NormalizedSourceItem:
    if len(group) <= 1:
        duplicate_cluster = SourceDuplicateCluster(
            cluster_id=None,
            cluster_size=1,
            duplicate_item_ids=[],
            same_event_cluster=False,
        )
        metadata = dict(kept_item.metadata)
        metadata["duplicate_cluster"] = duplicate_cluster.to_dict()
        return replace(
            kept_item,
            ranking_signals=_ranking_signals(kept_item).with_duplicate_cluster(duplicate_cluster),
            metadata=metadata,
        )
    duplicate_group = _duplicate_group(group, kept_item, dropped_items)
    duplicate_cluster = SourceDuplicateCluster(
        cluster_id=duplicate_group.group_id,
        cluster_size=len(group),
        duplicate_item_ids=list(duplicate_group.duplicate_item_ids),
        reasons=list(duplicate_group.reasons),
        canonical_urls=list(duplicate_group.canonical_urls),
        same_event_cluster=_is_same_event_cluster(duplicate_group),
    )
    metadata = dict(kept_item.metadata)
    metadata["duplicate_cluster"] = duplicate_cluster.to_dict()
    return replace(
        kept_item,
        ranking_signals=_ranking_signals(kept_item).with_duplicate_cluster(duplicate_cluster),
        metadata=metadata,
    )


def _ranking_signals(item: NormalizedSourceItem) -> SourceRankingSignals:
    return item.ranking_signals or SourceRankingSignals.from_metadata(item.metadata)


def _is_same_event_cluster(group: DuplicateGroup) -> bool:
    if len(group.canonical_urls) <= 1:
        return False
    return any(
        reason in {"title_hash", "content_hash", "near_duplicate_title"}
        for reason in group.reasons
    )


def _near_duplicate_title(left_title: str, right_title: str) -> bool:
    left_terms = _title_terms(left_title)
    right_terms = _title_terms(right_title)
    if (
        len(left_terms) < NEAR_DUPLICATE_MIN_TITLE_TERMS
        or len(right_terms) < NEAR_DUPLICATE_MIN_TITLE_TERMS
    ):
        return False
    intersection = left_terms.intersection(right_terms)
    union = left_terms.union(right_terms)
    if not union:
        return False
    jaccard = len(intersection) / len(union)
    containment = len(intersection) / min(len(left_terms), len(right_terms))
    return jaccard >= NEAR_DUPLICATE_TITLE_THRESHOLD and containment >= NEAR_DUPLICATE_TITLE_THRESHOLD


def _title_terms(title: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9]+", title.casefold()))
    return {term for term in terms if len(term) > 1 and term not in TITLE_STOPWORDS}


def _retention_priority(item: NormalizedSourceItem) -> tuple[int, float, int, int, int]:
    return (
        RELIABILITY_PRIORITY[item.source_reliability],
        _timestamp(item.published_at or item.fetched_at),
        _content_completeness(item),
        _official_source_score(item),
        _canonical_url_score(item),
    )


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).timestamp()


def _content_completeness(item: NormalizedSourceItem) -> int:
    summary = item.normalized_summary or item.summary or ""
    return len(summary)


def _official_source_score(item: NormalizedSourceItem) -> int:
    metadata = item.metadata
    if _truthy(metadata.get("official_source")) or _truthy(metadata.get("official_blog")):
        return 1
    for key in ("source_kind", "kind", "category"):
        marker = str(metadata.get(key) or "").casefold().replace("-", "_").replace(" ", "_")
        if marker in {"official", "official_blog"}:
            return 1
    return 0


def _canonical_url_score(item: NormalizedSourceItem) -> int:
    return int(item.url == item.canonical_url)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}
