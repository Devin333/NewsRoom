from __future__ import annotations

from pydantic import Field

from backend.foundation.models.object_ref import ObjectRef
from backend.foundation.primitives import PrimitiveModel, Score, TimeWindow
from backend.foundation.taxonomy import ImpactArea, MaturityStage, TrendDirection
from backend.foundation.models.quality_loop import (
    BusinessQualityCheck,
    BusinessQualitySnapshot,
    quality_snapshot_from_checks,
)


class Trend(PrimitiveModel):
    target_ref: ObjectRef
    time_window: TimeWindow
    score: Score
    direction: TrendDirection
    signal_count: int
    previous_signal_count: int | None = None
    growth_rate: float | None = None
    explanation: str


class Quality(PrimitiveModel):
    target_ref: ObjectRef
    score: Score
    dimensions: dict[str, Score] = Field(default_factory=dict)
    explanation: str


class Maturity(PrimitiveModel):
    technology_ref: ObjectRef
    stage: MaturityStage
    score: Score
    evidence_summary: str
    supporting_relations: list[str] = Field(default_factory=list)


class Impact(PrimitiveModel):
    target_ref: ObjectRef
    score: Score
    impact_areas: list[ImpactArea] = Field(default_factory=list)
    explanation: str


__all__ = [
    "BusinessQualityCheck",
    "BusinessQualitySnapshot",
    "Impact",
    "Maturity",
    "Quality",
    "Trend",
    "quality_snapshot_from_checks",
]
