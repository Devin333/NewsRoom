from __future__ import annotations

from datetime import datetime, timezone as _tz
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator

from business.foundation.primitives.base import PrimitiveModel
from business.foundation.primitives.ids import build_stable_id
from business.foundation.primitives.time_window import ensure_utc
from business.foundation.taxonomy import SourceReliability, SourceType


UTC = _tz.utc


class SourceRef(PrimitiveModel):
    source_name: str
    source_type: SourceType
    url: str | None = None
    reliability: SourceReliability = SourceReliability.UNKNOWN
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_id: str | None = None
    source_url: str | None = None
    external_id: str | None = None

    @field_validator("source_name")
    @classmethod
    def _validate_source_name(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("source_name is required")
        return text

    @model_validator(mode="after")
    def _normalize_reference(self) -> "SourceRef":
        url = self.url or self.source_url
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "source_url", url)
        object.__setattr__(self, "collected_at", ensure_utc(self.collected_at) or self.collected_at)
        if not self.source_id:
            object.__setattr__(
                self,
                "source_id",
                build_stable_id("src", self.source_type.value, self.source_name, url or ""),
            )
        return self


def canonicalize_url(url: str, base_url: str | None = None) -> str:
    candidate = str(url).strip()
    if not candidate:
        return ""
    if base_url:
        candidate = urljoin(base_url, candidate)
    parts = urlsplit(candidate)
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold()
    if not scheme or not host:
        return candidate
    port = parts.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path or ""
    query = _normalize_query(parts.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_query(query: str) -> str:
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.casefold()
        if normalized_key.startswith("utm_") or normalized_key in {"fbclid", "gclid"}:
            continue
        pairs.append((normalized_key, value))
    pairs.sort()
    return urlencode(pairs, doseq=True)


__all__ = ["SourceRef", "canonicalize_url"]
