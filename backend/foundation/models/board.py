from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation.models.object_ref import ObjectRef
from backend.foundation.models.relation import Relation
from backend.foundation.primitives import Confidence, PrimitiveModel, Score, SourceRef, ensure_utc
from backend.foundation.taxonomy import BoardType, DetailSectionType, TrendDirection


UTC = _tz.utc


class Badge(PrimitiveModel):
    label: str
    tone: str = "neutral"
    value: str | None = None
    description: str | None = None


class DisplayMetric(PrimitiveModel):
    label: str
    value: str | int | float
    unit: str | None = None
    trend: TrendDirection | None = None
    description: str | None = None


class BoardCard(PrimitiveModel):
    card_id: str
    board_type: BoardType
    title: str
    subtitle: str | None = None
    summary: str
    primary_object_ref: ObjectRef
    badges: list[Badge] = Field(default_factory=list)
    metrics: list[DisplayMetric] = Field(default_factory=list)
    related_refs: list[ObjectRef] = Field(default_factory=list)
    score: Score
    confidence: Confidence
    published_at: datetime | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ranking_reason: str | None = None
    ranking_features: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    relation_refs: list[SourceRef] = Field(default_factory=list)
    insight_refs: list[SourceRef] = Field(default_factory=list)
    provenance: Any | None = None
    quality: Any | None = None
    feedback_refs: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("card_id", "title", "summary")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("card fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "BoardCard":
        object.__setattr__(self, "published_at", ensure_utc(self.published_at))
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at) or self.generated_at)
        return self


class DetailSection(PrimitiveModel):
    title: str
    section_type: DetailSectionType
    content: str | None = None
    cards: list[BoardCard] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    metrics: list[DisplayMetric] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DetailPage(PrimitiveModel):
    page_id: str
    board_type: BoardType
    title: str
    summary: str
    primary_object_ref: ObjectRef
    sections: list[DetailSection] = Field(default_factory=list)
    related_cards: list[BoardCard] = Field(default_factory=list)
    insights: list[Any] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("page_id", "title", "summary")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("detail page fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "DetailPage":
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at) or self.generated_at)
        return self


__all__ = ["Badge", "BoardCard", "DetailPage", "DetailSection", "DisplayMetric"]
