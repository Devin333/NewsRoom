from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from business.foundation.taxonomy import SourceReliability


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid"}
FUTURE_PUBLISHED_AT_TOLERANCE = timedelta(minutes=5)

RELIABILITY_SCORE = {
    SourceReliability.OFFICIAL: 1.0,
    SourceReliability.HIGH: 1.0,
    SourceReliability.MEDIUM: 0.7,
    SourceReliability.UNKNOWN: 0.7,
    SourceReliability.LOW: 0.4,
}
RELIABILITY_PRIORITY = {
    SourceReliability.OFFICIAL: 4,
    SourceReliability.HIGH: 3,
    SourceReliability.MEDIUM: 2,
    SourceReliability.UNKNOWN: 2,
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

_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
_ENGLISH_STOPWORDS = {"and", "for", "from", "in", "of", "on", "the", "to", "with"}


@dataclass(frozen=True)
class SignalLineage:
    source_id: str
    source_item_id: str | None = None
    normalized_item_id: str | None = None
    ranked_item_id: str | None = None
    raw_url: str | None = None
    canonical_url: str | None = None
    fetched_at: datetime | None = None
    published_at: datetime | None = None
    raw_artifact_ref: Any | None = None
    parse_artifact_ref: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
            "normalized_item_id": self.normalized_item_id,
            "ranked_item_id": self.ranked_item_id,
            "raw_url": self.raw_url,
            "canonical_url": self.canonical_url,
            "fetched_at": _dt(self.fetched_at),
            "published_at": _dt(self.published_at),
            "raw_artifact_ref": _artifact_ref(self.raw_artifact_ref),
            "parse_artifact_ref": _artifact_ref(self.parse_artifact_ref),
            "metadata": dict(self.metadata),
        }
        return {key: value for key, value in payload.items() if value not in (None, {}, [])}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SignalLineage":
        return cls(
            source_id=str(payload.get("source_id") or "source"),
            source_item_id=_optional_str(payload.get("source_item_id")),
            normalized_item_id=_optional_str(payload.get("normalized_item_id")),
            ranked_item_id=_optional_str(payload.get("ranked_item_id")),
            raw_url=_optional_str(payload.get("raw_url")),
            canonical_url=_optional_str(payload.get("canonical_url")),
            fetched_at=_parse_datetime_optional(payload.get("fetched_at")),
            published_at=_parse_datetime_optional(payload.get("published_at")),
            raw_artifact_ref=payload.get("raw_artifact_ref"),
            parse_artifact_ref=payload.get("parse_artifact_ref"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RawSourceItem:
    source_item_id: str
    source_id: str
    source_name: str
    source_type: Any
    title: str
    url: str
    fetched_at: datetime
    published_at: datetime | None = None
    summary: str | None = None
    raw_content: str | None = None
    raw_artifact_ref: Any | None = None
    parse_artifact_ref: Any | None = None
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    lineage: SignalLineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", _source_type_value(self.source_type))
        object.__setattr__(self, "fetched_at", _as_utc(self.fetched_at))
        object.__setattr__(self, "published_at", _parse_datetime_optional(self.published_at))
        object.__setattr__(self, "authors", _string_list(self.authors))
        object.__setattr__(self, "tags", _string_list(self.tags))
        if self.lineage is None:
            object.__setattr__(
                self,
                "lineage",
                SignalLineage(
                    source_id=self.source_id,
                    source_item_id=self.source_item_id,
                    raw_url=self.url,
                    fetched_at=self.fetched_at,
                    published_at=self.published_at,
                    raw_artifact_ref=self.raw_artifact_ref,
                    parse_artifact_ref=self.parse_artifact_ref,
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": _source_type_value(self.source_type),
            "title": self.title,
            "url": self.url,
            "fetched_at": _dt(self.fetched_at),
            "published_at": _dt(self.published_at),
            "summary": self.summary,
            "raw_content": self.raw_content,
            "raw_artifact_ref": _artifact_ref(self.raw_artifact_ref),
            "parse_artifact_ref": _artifact_ref(self.parse_artifact_ref),
            "authors": list(self.authors),
            "tags": list(self.tags),
            "language": self.language,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class NormalizedSourceItem:
    normalized_item_id: str
    source_item_id: str
    source_id: str
    title: str
    normalized_title: str
    url: str
    canonical_url: str
    canonical_url_hash: str
    title_hash: str
    content_hash: str
    source_reliability: SourceReliability
    fetched_at: datetime
    published_at: datetime | None = None
    summary: str | None = None
    normalized_summary: str | None = None
    language: str | None = None
    lineage: SignalLineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_reliability", _source_reliability(self.source_reliability))
        object.__setattr__(self, "fetched_at", _as_utc(self.fetched_at))
        object.__setattr__(self, "published_at", _parse_datetime_optional(self.published_at))
        if self.lineage is None:
            metadata_lineage = self.metadata.get("lineage") if isinstance(self.metadata.get("lineage"), dict) else None
            lineage = SignalLineage.from_dict(metadata_lineage) if metadata_lineage else SignalLineage(
                source_id=self.source_id,
                source_item_id=self.source_item_id,
                normalized_item_id=self.normalized_item_id,
                raw_url=self.url,
                canonical_url=self.canonical_url,
                fetched_at=self.fetched_at,
                published_at=self.published_at,
            )
            object.__setattr__(self, "lineage", lineage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_item_id": self.normalized_item_id,
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "title": self.title,
            "normalized_title": self.normalized_title,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "canonical_url_hash": self.canonical_url_hash,
            "title_hash": self.title_hash,
            "content_hash": self.content_hash,
            "source_reliability": self.source_reliability.value,
            "fetched_at": _dt(self.fetched_at),
            "published_at": _dt(self.published_at),
            "summary": self.summary,
            "normalized_summary": self.normalized_summary,
            "language": self.language,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RankedSourceItem:
    ranked_item_id: str
    item: NormalizedSourceItem
    relevance_score: float
    recency_score: float
    reliability_score: float
    novelty_score: float
    final_score: float
    authority_score: float = 0.0
    duplicate_cluster_score: float = 0.0
    historical_importance_score: float = 0.0
    subscription_match_score: float = 0.0
    source_quality_score: float | None = None
    rank_reason: str = ""
    lineage: SignalLineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lineage is None:
            metadata_lineage = self.metadata.get("lineage") if isinstance(self.metadata.get("lineage"), dict) else None
            if metadata_lineage is not None:
                object.__setattr__(self, "lineage", SignalLineage.from_dict(metadata_lineage))
                return
            item_lineage = self.item.lineage
            object.__setattr__(
                self,
                "lineage",
                SignalLineage(
                    source_id=self.item.source_id,
                    source_item_id=self.item.source_item_id,
                    normalized_item_id=self.item.normalized_item_id,
                    ranked_item_id=self.ranked_item_id,
                    raw_url=self.item.url,
                    canonical_url=self.item.canonical_url,
                    fetched_at=self.item.fetched_at,
                    published_at=self.item.published_at,
                    raw_artifact_ref=item_lineage.raw_artifact_ref if item_lineage else None,
                    parse_artifact_ref=item_lineage.parse_artifact_ref if item_lineage else None,
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranked_item_id": self.ranked_item_id,
            "item": self.item.to_dict(),
            "relevance_score": self.relevance_score,
            "recency_score": self.recency_score,
            "reliability_score": self.reliability_score,
            "novelty_score": self.novelty_score,
            "final_score": self.final_score,
            "authority_score": self.authority_score,
            "duplicate_cluster_score": self.duplicate_cluster_score,
            "historical_importance_score": self.historical_importance_score,
            "subscription_match_score": self.subscription_match_score,
            "source_quality_score": self.source_quality_score,
            "rank_reason": self.rank_reason,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DuplicateGroup:
    group_id: str
    kept_item_id: str
    duplicate_item_ids: list[str]
    reasons: list[str] = field(default_factory=list)
    canonical_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "kept_item_id": self.kept_item_id,
            "duplicate_item_ids": list(self.duplicate_item_ids),
            "reasons": list(self.reasons),
            "canonical_urls": list(self.canonical_urls),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DedupResult:
    kept_items: list[NormalizedSourceItem]
    duplicate_groups: list[DuplicateGroup]
    dropped_items: list[NormalizedSourceItem]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept_item_count": len(self.kept_items),
            "duplicate_group_count": len(self.duplicate_groups),
            "dropped_item_count": len(self.dropped_items),
            "kept_item_ids": [item.normalized_item_id for item in self.kept_items],
            "dropped_item_ids": [item.normalized_item_id for item in self.dropped_items],
            "duplicate_groups": [group.to_dict() for group in self.duplicate_groups],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceItemQualityScore:
    normalized_item_id: str
    source_item_id: str
    source_id: str
    quality_score: float
    reliability_score: float
    authority_score: float
    traceability_score: float
    freshness_score: float
    content_score: float
    language_score: float
    penalties: list[str] = field(default_factory=list)
    score_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_item_id": self.normalized_item_id,
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "quality_score": self.quality_score,
            "reliability_score": self.reliability_score,
            "authority_score": self.authority_score,
            "traceability_score": self.traceability_score,
            "freshness_score": self.freshness_score,
            "content_score": self.content_score,
            "language_score": self.language_score,
            "penalties": list(self.penalties),
            "score_reason": self.score_reason,
        }


def normalize_items(items: list[RawSourceItem]) -> list[NormalizedSourceItem]:
    return [normalize_item(item) for item in items]


def normalize_item(item: RawSourceItem) -> NormalizedSourceItem:
    canonical_url = canonicalize_source_url(item.url)
    normalized_title = normalize_text(item.title)
    normalized_summary = normalize_text(item.summary) if item.summary else None
    reliability = _source_reliability(item.metadata.get("source_reliability", "medium"))
    metadata = dict(item.metadata)
    metadata.setdefault("source_type", _source_type_value(item.source_type))
    metadata.setdefault("source_id", item.source_id)
    metadata.setdefault("source_name", item.source_name)
    metadata.setdefault("authors", list(item.authors))
    metadata.setdefault("tags", list(item.tags))
    if item.tags:
        metadata["tags"] = list(item.tags)
    detected_language = None if item.language else detect_language(_language_detection_text(item))
    language = item.language or detected_language or "unknown"
    if item.language is None:
        if detected_language is None:
            metadata["language_normalization"] = {
                "fallback_applied": True,
                "language": language,
            }
        else:
            metadata["language_normalization"] = {
                "fallback_applied": False,
                "detection_applied": True,
                "language": language,
            }
    published_at, time_metadata = _normalize_published_at(item.published_at, item.fetched_at)
    if time_metadata:
        metadata["time_normalization"] = time_metadata
    lineage = {
        "source_id": item.source_id,
        "source_item_id": item.source_item_id,
        "raw_url": item.url,
        "canonical_url": canonical_url,
        "fetched_at": _dt(item.fetched_at),
        "published_at": _dt(published_at),
    }
    raw_artifact_ref = _artifact_ref(item.raw_artifact_ref)
    if raw_artifact_ref is not None:
        lineage["raw_artifact_ref"] = raw_artifact_ref
    parse_artifact_ref = _artifact_ref(item.parse_artifact_ref)
    if parse_artifact_ref is not None:
        lineage["parse_artifact_ref"] = parse_artifact_ref
    metadata["lineage"] = lineage
    lineage_obj = SignalLineage.from_dict(lineage)
    return NormalizedSourceItem(
        normalized_item_id=f"norm_{_hash(item.source_item_id + canonical_url)[:16]}",
        source_item_id=item.source_item_id,
        source_id=item.source_id,
        title=item.title,
        normalized_title=normalized_title,
        url=item.url,
        canonical_url=canonical_url,
        canonical_url_hash=_hash(canonical_url),
        title_hash=_hash(normalized_title),
        content_hash=_content_hash(normalized_title, normalized_summary),
        source_reliability=reliability,
        fetched_at=item.fetched_at,
        published_at=published_at,
        summary=item.summary,
        normalized_summary=normalized_summary,
        language=language,
        lineage=lineage_obj,
        metadata=metadata,
    )


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


def score_source_item(
    item: NormalizedSourceItem,
    *,
    now: datetime | None = None,
) -> SourceItemQualityScore:
    current_time = now or datetime.now(UTC)
    reliability = RELIABILITY_SCORE[_source_reliability(item.source_reliability)]
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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def canonicalize_source_url(url: str, *, base_url: str | None = None) -> str:
    raw_url = str(url).strip()
    if base_url:
        raw_url = urljoin(base_url.strip(), raw_url)
    parts = urlsplit(raw_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_KEYS and not key.startswith(TRACKING_PREFIXES)
    ]
    normalized_path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            _canonical_netloc(parts),
            normalized_path,
            urlencode(sorted(query)),
            "",
        )
    )


def detect_language(text: str) -> str | None:
    content = " ".join(text.split())
    if not content:
        return None
    zh_count = _count_range(content, 0x4E00, 0x9FFF)
    ja_count = _count_range(content, 0x3040, 0x30FF)
    ko_count = _count_range(content, 0xAC00, 0xD7AF)
    if zh_count >= 2 and zh_count >= ja_count and zh_count >= ko_count:
        return "zh"
    if ja_count >= 2 and ja_count >= ko_count:
        return "ja"
    if ko_count >= 2:
        return "ko"
    words = [word.casefold() for word in _LATIN_WORD_RE.findall(content)]
    stopword_hits = {word for word in words if word in _ENGLISH_STOPWORDS}
    if len(words) >= 8 and len(stopword_hits) >= 2:
        return "en"
    return None


def lineage_from_item(item: NormalizedSourceItem, *, ranked_item_id: str) -> SignalLineage:
    lineage = item.lineage
    return SignalLineage(
        source_id=item.source_id,
        source_item_id=item.source_item_id,
        normalized_item_id=item.normalized_item_id,
        ranked_item_id=ranked_item_id,
        raw_url=item.url,
        canonical_url=item.canonical_url,
        fetched_at=item.fetched_at,
        published_at=item.published_at,
        raw_artifact_ref=lineage.raw_artifact_ref if lineage else None,
        parse_artifact_ref=lineage.parse_artifact_ref if lineage else None,
    )


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
    reliability = RELIABILITY_SCORE[_source_reliability(item.source_reliability)]
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


def _normalize_published_at(
    published_at: datetime | None,
    fetched_at: datetime,
) -> tuple[datetime | None, dict[str, object]]:
    if published_at is None:
        return None, {}
    published_at_utc = _as_utc(published_at)
    fetched_at_utc = _as_utc(fetched_at)
    if published_at_utc <= fetched_at_utc + FUTURE_PUBLISHED_AT_TOLERANCE:
        return published_at_utc, {}
    return fetched_at_utc, {
        "future_timestamp_detected": True,
        "original_published_at": _dt(published_at_utc),
        "published_at_normalized_to": "fetched_at",
    }


def _language_detection_text(item: RawSourceItem) -> str:
    return " ".join(part for part in [item.title, item.summary or "", item.raw_content or ""] if part)


def _content_hash(normalized_title: str, normalized_summary: str | None) -> str:
    return _hash(normalized_summary or normalized_title)


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
        group_id=f"dup_{hashlib.sha256('|'.join(item_ids).encode('utf-8')).hexdigest()[:16]}",
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
        metadata = dict(kept_item.metadata)
        metadata.setdefault(
            "duplicate_cluster",
            {
                "cluster_id": None,
                "cluster_size": 1,
                "duplicate_item_ids": [],
                "same_event_cluster": False,
            },
        )
        return replace(kept_item, metadata=metadata)
    duplicate_group = _duplicate_group(group, kept_item, dropped_items)
    metadata = dict(kept_item.metadata)
    metadata["duplicate_cluster"] = {
        "cluster_id": duplicate_group.group_id,
        "cluster_size": len(group),
        "duplicate_item_ids": list(duplicate_group.duplicate_item_ids),
        "reasons": list(duplicate_group.reasons),
        "canonical_urls": list(duplicate_group.canonical_urls),
        "same_event_cluster": _is_same_event_cluster(duplicate_group),
    }
    return replace(kept_item, metadata=metadata)


def _is_same_event_cluster(group: DuplicateGroup) -> bool:
    if len(group.canonical_urls) <= 1:
        return False
    return any(reason in {"title_hash", "content_hash", "near_duplicate_title"} for reason in group.reasons)


def _near_duplicate_title(left_title: str, right_title: str) -> bool:
    left_terms = _title_terms(left_title)
    right_terms = _title_terms(right_title)
    if len(left_terms) < NEAR_DUPLICATE_MIN_TITLE_TERMS or len(right_terms) < NEAR_DUPLICATE_MIN_TITLE_TERMS:
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
        RELIABILITY_PRIORITY[_source_reliability(item.source_reliability)],
        _timestamp(item.published_at or item.fetched_at),
        _content_completeness(item),
        _official_source_score(item),
        _canonical_url_score(item),
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
    age_days = max(0.0, (_as_utc(now) - _as_utc(timestamp)).total_seconds() / 86400)
    if age_days <= 1:
        return 1.0
    if age_days >= 14:
        return 0.2
    return 1.0 - (age_days - 1) * (0.8 / 13)


def _authority(item: NormalizedSourceItem) -> float:
    return _authority_score(item)


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


def _authority_score(item: NormalizedSourceItem) -> float:
    try:
        value = float(item.metadata.get("source_authority_score", 0.5))
    except (TypeError, ValueError):
        value = 0.5
    return _clamp(value)


def _traceability_score(item: NormalizedSourceItem) -> float:
    raw_lineage = item.metadata.get("lineage")
    lineage = raw_lineage if isinstance(raw_lineage, dict) else {}
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
    if _source_reliability(item.source_reliability) == SourceReliability.LOW:
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


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return _as_utc(value).timestamp()


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


def _canonical_netloc(parts: Any) -> str:
    scheme = parts.scheme.lower()
    host = (parts.hostname or parts.netloc).lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host
    return f"{host}:{port}"


def _count_range(text: str, start: int, end: int) -> int:
    return sum(1 for char in text if start <= ord(char) <= end)


def _source_type_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value).strip().casefold()
    text = str(value or "rss").strip().casefold()
    return text or "rss"


def _source_reliability(value: Any) -> SourceReliability:
    if isinstance(value, SourceReliability):
        return value
    text = str(getattr(value, "value", value) or "medium").strip().casefold()
    try:
        return SourceReliability(text)
    except ValueError:
        return SourceReliability.UNKNOWN


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _artifact_ref(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime_optional(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []
