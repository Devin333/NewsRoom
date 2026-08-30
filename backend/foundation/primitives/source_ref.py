from __future__ import annotations

from datetime import datetime, timezone as _tz
from urllib.parse import SplitResult, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator

from backend.foundation.primitives.base import PrimitiveModel
from backend.foundation.primitives.ids import build_stable_id
from backend.foundation.primitives.time_window import ensure_utc
from backend.foundation.taxonomy import SourceReliability, SourceType


UTC = _tz.utc
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid"}


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
        raw_url = self.url or self.source_url
        url = canonicalize_url(raw_url) if raw_url else None
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

    input_parts = _split_source_url(candidate)
    if not input_parts.scheme:
        normalized_base = str(base_url).strip() if base_url else ""
        if not normalized_base:
            return candidate
        base_parts = _split_source_url(normalized_base)
        if not base_parts.scheme or not base_parts.hostname:
            return candidate
        candidate = urljoin(normalized_base, candidate)
        parts = _split_source_url(candidate)
        if not parts.scheme or not parts.hostname:
            return str(url).strip()
    else:
        parts = input_parts

    scheme = parts.scheme.casefold()
    host = _source_hostname(parts, candidate)
    port = _source_port(parts, candidate)
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = formatted_host if port is None else f"{formatted_host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = _normalize_query(parts.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_query(query: str) -> str:
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.casefold()
        if normalized_key.startswith(_TRACKING_PREFIXES) or normalized_key in _TRACKING_KEYS:
            continue
        pairs.append((key, value))
    pairs.sort()
    return urlencode(pairs)


def source_url_read_aliases(
    stored_url: str,
    *,
    raw_url: str | None = None,
    base_url: str | None = None,
) -> tuple[str, ...]:
    """Return exact-first aliases for read-only comparison of historical identities."""

    exact = str(stored_url).strip()
    aliases: list[str] = []

    def add(value: str) -> None:
        if value not in aliases:
            aliases.append(value)

    add(exact)
    inputs = [exact]
    if raw_url is not None:
        raw = str(raw_url).strip()
        if raw not in inputs:
            inputs.append(raw)
    for candidate in inputs:
        for normalizer in (
            canonicalize_url,
            _canonicalize_url_foundation_v1,
            _canonicalize_url_signal_v1,
        ):
            try:
                add(normalizer(candidate, base_url=base_url))
            except (TypeError, ValueError):
                continue
    return tuple(aliases)


def _split_source_url(value: str) -> SplitResult:
    try:
        return urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"malformed Source URL: {value}") from exc


def _source_hostname(parts: SplitResult, value: str) -> str:
    try:
        host = parts.hostname
    except ValueError as exc:
        raise ValueError(f"malformed Source URL: {value}") from exc
    if not parts.scheme or not parts.netloc or not host or any(char.isspace() for char in host):
        raise ValueError(f"malformed Source URL: {value}")
    return host.casefold()


def _source_port(parts: SplitResult, value: str) -> int | None:
    authority = parts.netloc.rsplit("@", maxsplit=1)[-1]
    if authority.endswith(":"):
        raise ValueError(f"malformed Source URL: {value}")
    try:
        return parts.port
    except ValueError as exc:
        raise ValueError(f"malformed Source URL: {value}") from exc


def _canonicalize_url_foundation_v1(url: str, base_url: str | None = None) -> str:
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
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = key.casefold()
        if normalized_key.startswith("utm_") or normalized_key in _TRACKING_KEYS:
            continue
        pairs.append((normalized_key, value))
    pairs.sort()
    return urlunsplit((scheme, netloc, parts.path or "", urlencode(pairs, doseq=True), ""))


def _canonicalize_url_signal_v1(url: str, *, base_url: str | None = None) -> str:
    raw_url = url.strip()
    if base_url:
        raw_url = urljoin(base_url.strip(), raw_url)
    parts = urlsplit(raw_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_KEYS and not key.startswith(_TRACKING_PREFIXES)
    ]
    normalized_path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            _legacy_signal_netloc(parts),
            normalized_path,
            urlencode(sorted(query)),
            "",
        )
    )


def _legacy_signal_netloc(parts: SplitResult) -> str:
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


__all__ = ["SourceRef", "canonicalize_url"]
