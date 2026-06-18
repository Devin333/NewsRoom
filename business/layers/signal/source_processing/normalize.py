from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc

from business.foundation.models.source import (
    Lineage,
    NormalizedSourceItem,
    RawSourceItem,
    SourceRankingSignals,
    SourceReliability,
    SourceType,
)
from business.layers.signal.source_processing.language import detect_language
from business.layers.signal.source_processing.url_normalization import canonicalize_url


FUTURE_PUBLISHED_AT_TOLERANCE = timedelta(minutes=5)


def normalize_items(items: list[RawSourceItem]) -> list[NormalizedSourceItem]:
    return [normalize_item(item) for item in items]


def normalize_item(item: RawSourceItem) -> NormalizedSourceItem:
    canonical_url = canonicalize_url(item.url)
    normalized_title = normalize_text(item.title)
    normalized_summary = normalize_text(item.summary) if item.summary else None
    reliability = SourceReliability(item.metadata.get("source_reliability", "medium"))
    metadata = dict(item.metadata)
    metadata.setdefault("source_type", SourceType(item.source_type).value)
    metadata.setdefault("source_id", item.source_id)
    metadata.setdefault("source_name", item.source_name)
    metadata.setdefault("authors", list(item.authors))
    metadata.setdefault("tags", list(item.tags))
    if item.tags:
        metadata["tags"] = list(item.tags)
    ranking_signals = SourceRankingSignals.from_metadata(metadata, tags=item.tags)
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
    lineage_obj = Lineage.from_dict(lineage)
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
        ranking_signals=ranking_signals,
        lineage=lineage_obj,
        metadata=metadata,
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
    return " ".join(
        part
        for part in [item.title, item.summary or "", item.raw_content or ""]
        if part
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _content_hash(normalized_title: str, normalized_summary: str | None) -> str:
    return _hash(normalized_summary or normalized_title)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dt(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _artifact_ref(value):
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
