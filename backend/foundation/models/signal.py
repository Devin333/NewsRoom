from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation.primitives import (
    Confidence,
    PrimitiveModel,
    SourceRef,
    build_stable_id,
    canonicalize_url,
    ensure_utc,
    normalize_key,
)
from backend.foundation.taxonomy import BoardType, ProcessingStatus, SignalType


UTC = _tz.utc


class Signal(PrimitiveModel):
    signal_id: str
    signal_type: SignalType
    board_type: BoardType
    title: str
    summary: str | None = None
    content: str | None = None
    url: str | None = None
    language: str = "en"
    source: SourceRef
    authors: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    content_hash: str
    canonical_key: str
    processing_status: ProcessingStatus = ProcessingStatus.NEW
    confidence: Confidence | None = None

    @field_validator("signal_id", "title", "content_hash", "canonical_key")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("required signal fields must be non-empty")
        return text

    @field_validator("authors", "tags", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "Signal":
        object.__setattr__(self, "collected_at", ensure_utc(self.collected_at) or self.collected_at)
        object.__setattr__(self, "published_at", ensure_utc(self.published_at))
        return self


def make_signal_identity(
    *,
    signal_type: SignalType,
    board_type: BoardType,
    source: SourceRef,
    title: str,
    url: str | None = None,
    published_at: datetime | None = None,
) -> tuple[str, str, str]:
    canonical_url = canonicalize_url(url or "", base_url=source.source_url)
    canonical_key = normalize_key(
        "|".join(
            part
            for part in [
                board_type.value,
                signal_type.value,
                source.source_id,
                canonical_url or source.source_url or "",
                title,
                (published_at.isoformat() if published_at else ""),
            ]
            if part
        )
    )
    content_hash = build_stable_id("sig", board_type.value, signal_type.value, canonical_key)
    signal_id = build_stable_id("sig", signal_type.value, canonical_key, title)
    return signal_id, canonical_key, content_hash


__all__ = ["Signal", "SourceRef", "make_signal_identity"]
