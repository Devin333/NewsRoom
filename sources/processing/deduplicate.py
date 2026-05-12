from __future__ import annotations

import re
from datetime import UTC, datetime

from domain.sources import NormalizedSourceItem, SourceReliability


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

    return [max(group, key=_retention_priority) for group in groups]


def _is_duplicate(left: NormalizedSourceItem, right: NormalizedSourceItem) -> bool:
    return (
        left.canonical_url_hash == right.canonical_url_hash
        or left.title_hash == right.title_hash
        or left.content_hash == right.content_hash
        or _near_duplicate_title(left.normalized_title, right.normalized_title)
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
