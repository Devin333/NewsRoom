from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from domain.sources import NormalizedSourceItem, RawSourceItem, SourceReliability


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid"}
FUTURE_PUBLISHED_AT_TOLERANCE = timedelta(minutes=5)


def normalize_items(items: list[RawSourceItem]) -> list[NormalizedSourceItem]:
    return [normalize_item(item) for item in items]


def normalize_item(item: RawSourceItem) -> NormalizedSourceItem:
    canonical_url = canonicalize_url(item.url)
    normalized_title = normalize_text(item.title)
    normalized_summary = normalize_text(item.summary) if item.summary else None
    reliability = SourceReliability(item.metadata.get("source_reliability", "medium"))
    metadata = dict(item.metadata)
    published_at, time_metadata = _normalize_published_at(item.published_at, item.fetched_at)
    if time_metadata:
        metadata["time_normalization"] = time_metadata
    metadata["lineage"] = {
        "source_id": item.source_id,
        "source_item_id": item.source_item_id,
        "raw_url": item.url,
        "canonical_url": canonical_url,
        "fetched_at": _dt(item.fetched_at),
        "published_at": _dt(published_at),
    }
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
        language=item.language,
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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _content_hash(normalized_title: str, normalized_summary: str | None) -> str:
    return _hash(normalized_summary or normalized_title)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def canonicalize_url(url: str, *, base_url: str | None = None) -> str:
    raw_url = url.strip()
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


def _canonical_netloc(parts) -> str:
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


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dt(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
