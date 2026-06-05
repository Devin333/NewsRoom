from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation.models.object_ref import ObjectRef
from business.foundation.primitives import Confidence, PrimitiveModel, Score, TimeWindow, ensure_utc
from business.foundation.taxonomy import InsightType


UTC = _tz.utc


class Insight(PrimitiveModel):
    insight_id: str
    title: str
    summary: str
    insight_type: InsightType
    related_object_refs: list[ObjectRef] = Field(default_factory=list)
    evidence_relation_ids: list[str] = Field(default_factory=list)
    time_window: TimeWindow
    confidence: Confidence
    importance: Score
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("insight_id", "title", "summary")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("insight fields must be non-empty")
        return text

    @field_validator("evidence_relation_ids", mode="before")
    @classmethod
    def _coerce_evidence_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "Insight":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self


__all__ = ["Insight"]
