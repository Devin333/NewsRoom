from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation.models.board import BoardCard, DetailPage, DisplayMetric
from backend.foundation.models.insight import Insight
from backend.foundation.models.object_ref import ObjectRef
from backend.foundation.primitives import PrimitiveModel, ensure_utc
from backend.foundation.taxonomy import BoardType, DetailSectionType, ReportType


UTC = _tz.utc


class ReportSection(PrimitiveModel):
    title: str
    section_type: DetailSectionType
    content: str | None = None
    cards: list[BoardCard] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    related_refs: list[ObjectRef] = Field(default_factory=list)
    metrics: list[DisplayMetric] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Report(PrimitiveModel):
    report_id: str
    report_type: ReportType
    board_type: BoardType
    title: str
    summary: str
    sections: list[ReportSection] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    cards: list[BoardCard] = Field(default_factory=list)
    detail_pages: list[DetailPage] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("report_id", "title", "summary")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("report fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "Report":
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at) or self.generated_at)
        return self


__all__ = ["Report", "ReportSection"]
