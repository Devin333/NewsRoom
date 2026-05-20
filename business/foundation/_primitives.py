from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from business.foundation.taxonomy import ConfidenceMethod, ScoreLevel, SourceReliability, SourceType


class PrimitiveModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class ScoreFactor(PrimitiveModel):
    name: str
    value: float
    weight: float = 1.0
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("score factor name is required")
        return text

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("score factor value must be between 0 and 1")
        return numeric

    @field_validator("weight")
    @classmethod
    def _validate_weight(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0:
            raise ValueError("score factor weight must be non-negative")
        return numeric


class BusinessId(PrimitiveModel):
    value: str
    namespace: str

    @field_validator("value", "namespace")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("business id fields must be non-empty")
        return text

    @classmethod
    def stable(cls, namespace: str, *parts: Any, prefix: str | None = None) -> "BusinessId":
        return cls(namespace=normalize_key(namespace), value=build_stable_id(prefix or namespace, *parts))


class _BoundedScore(PrimitiveModel):
    value: float
    factors: list[ScoreFactor] = Field(default_factory=list)
    explanation: str | None = None

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("score value must be between 0 and 1")
        return round(numeric, 4)

    @computed_field
    @property
    def level(self) -> ScoreLevel:
        return score_level(self.value)


class Score(_BoundedScore):
    pass


class Confidence(_BoundedScore):
    reason: str = ""
    evidence_count: int = 0
    method: ConfidenceMethod = ConfidenceMethod.RULE_BASED

    @field_validator("evidence_count")
    @classmethod
    def _validate_evidence_count(cls, value: int) -> int:
        numeric = int(value)
        if numeric < 0:
            raise ValueError("confidence evidence_count must be non-negative")
        return numeric


class TextSpan(PrimitiveModel):
    start: int
    end: int
    text: str | None = None
    source_text: str | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "TextSpan":
        if self.start < 0:
            raise ValueError("text span start must be non-negative")
        if self.end < self.start:
            raise ValueError("text span end must be greater than or equal to start")
        return self


class TimeWindow(PrimitiveModel):
    start: datetime = Field(alias="start_at")
    end: datetime = Field(alias="end_at")
    label: str | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "TimeWindow":
        start = ensure_utc(self.start) or self.start
        end = ensure_utc(self.end) or self.end
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if end < start:
            raise ValueError("time window end must be greater than or equal to start")
        return self

    def contains(self, value: datetime) -> bool:
        instant = ensure_utc(value) or value
        return self.start <= instant <= self.end

    @property
    def start_at(self) -> datetime:
        return self.start

    @property
    def end_at(self) -> datetime:
        return self.end


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


def build_stable_id(prefix: str, *parts: Any, length: int = 12) -> str:
    normalized = "|".join(_normalize_part(part) for part in parts)
    digest = sha1(normalized.encode("utf-8")).hexdigest()[:length]
    clean_prefix = normalize_key(prefix) or "id"
    return f"{clean_prefix}_{digest}"


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


def normalize_key(text: str) -> str:
    value = str(text).strip().casefold()
    value = value.replace("&", " and ")
    value = "".join(ch if ch.isalnum() else "_" for ch in value)
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("_")


def slugify(text: str) -> str:
    value = normalize_key(text)
    return value.replace("_", "-")


def stable_business_id(namespace: str, *parts: Any, prefix: str | None = None) -> BusinessId:
    return BusinessId.stable(namespace, *parts, prefix=prefix)


def score_level(value: float) -> ScoreLevel:
    numeric = float(value)
    if numeric >= 0.8:
        return ScoreLevel.VERY_HIGH
    if numeric >= 0.6:
        return ScoreLevel.HIGH
    if numeric >= 0.4:
        return ScoreLevel.MEDIUM
    if numeric >= 0.2:
        return ScoreLevel.LOW
    return ScoreLevel.VERY_LOW


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_part(part: Any) -> str:
    if isinstance(part, BaseModel):
        return repr(part.model_dump(mode="json", exclude_none=True))
    if isinstance(part, dict):
        return repr(sorted((str(key), _normalize_part(value)) for key, value in part.items()))
    if isinstance(part, (list, tuple, set)):
        return repr([_normalize_part(value) for value in part])
    return str(part).strip().casefold()


def _normalize_query(query: str) -> str:
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.casefold()
        if normalized_key.startswith("utm_") or normalized_key in {"fbclid", "gclid"}:
            continue
        pairs.append((normalized_key, value))
    pairs.sort()
    return urlencode(pairs, doseq=True)
