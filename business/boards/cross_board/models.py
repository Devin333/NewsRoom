from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field

from business.foundation import (
    BoardCard,
    BoardType,
    Confidence,
    Impact,
    Insight,
    Maturity,
    ObjectRef,
    PrimitiveModel,
    Relation,
    RelationType,
    BusinessQualitySnapshot,
    BusinessRegressionGuardResult,
    TimeWindow,
    Trend,
)
from business.layers.analysis import TechnologyRadarItem


class CrossBoardQuery(PrimitiveModel):
    object_ref: ObjectRef | None = None
    technology_ref: ObjectRef | None = None
    board_types: list[BoardType] = Field(default_factory=list)
    relation_types: list[RelationType] = Field(default_factory=list)
    time_window: TimeWindow
    limit: int = 20


class RelationView(PrimitiveModel):
    relation_id: str
    relation_type: RelationType
    source_label: str
    target_label: str
    explanation: str
    confidence: Confidence


class CrossBoardRelationView(PrimitiveModel):
    source_board: BoardType
    target_board: BoardType
    relation: RelationView
    source_card: BoardCard | None = None
    target_card: BoardCard | None = None
    explanation: str


class TechnologyJourneyStage(PrimitiveModel):
    stage_type: str
    title: str
    object_refs: list[ObjectRef] = Field(default_factory=list)
    evidence_relation_ids: list[str] = Field(default_factory=list)
    time_range: TimeWindow | None = None
    summary: str = ""


class TechnologyJourney(PrimitiveModel):
    technology_ref: ObjectRef
    technology_name: str
    stages: list[TechnologyJourneyStage] = Field(default_factory=list)
    maturity: Maturity | None = None
    trend: Trend | None = None
    impact: Impact | None = None
    summary: str = ""
    guard_result: BusinessRegressionGuardResult | None = None


class CrossBoardInsight(PrimitiveModel):
    insight: Insight
    relation_views: list[CrossBoardRelationView] = Field(default_factory=list)
    primary_technology: ObjectRef | None = None
    board_support: dict[str, list[str]] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    guard_result: BusinessRegressionGuardResult | None = None
    quality_summary: BusinessQualitySnapshot | None = None


class TechnologyRadarRequest(PrimitiveModel):
    time_window: TimeWindow
    categories: list[str] = Field(default_factory=list)
    min_trend_score: float = 0.0
    limit: int = 50


class TechnologyRadarOutput(PrimitiveModel):
    radar_items: list[TechnologyRadarItem] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
