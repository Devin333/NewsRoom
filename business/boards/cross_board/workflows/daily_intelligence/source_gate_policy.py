from __future__ import annotations

from typing import Any

from business.layers.signal.source_processing.governance import COMMUNITY_CATEGORIES, COMMUNITY_SOURCE_TYPES


SOCIAL_MEDIA_DOMAINS = (
    "reddit.com",
    "news.ycombinator.com",
    "lobste.rs",
    "stackoverflow.com",
    "dev.to",
    "medium.com",
)


def contains_social_media_evidence(evidence_bundle: Any) -> bool:
    for item in getattr(evidence_bundle, "items", []) or []:
        if is_social_media_evidence(item):
            return True
    return False


def is_social_media_evidence(item: Any) -> bool:
    metadata = dict(getattr(item, "metadata", {}) or {})
    source_type = str(metadata.get("source_type") or "").strip().casefold()
    category = _normalize_category(metadata.get("category"))
    if source_type in COMMUNITY_SOURCE_TYPES or category in COMMUNITY_CATEGORIES:
        return True
    source_url = str(getattr(item, "source_url", "") or "").casefold()
    return any(domain in source_url for domain in SOCIAL_MEDIA_DOMAINS)


def _normalize_category(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).casefold().replace("-", " ").replace("_", " ").split()).replace(" ", "_")


__all__ = ["contains_social_media_evidence", "is_social_media_evidence"]
