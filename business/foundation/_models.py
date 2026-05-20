from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation.primitives import Confidence, PrimitiveModel, Score, SourceRef, TextSpan, TimeWindow, build_stable_id, canonicalize_url, ensure_utc, normalize_key
from business.foundation.taxonomy import (
    BoardType,
    ClaimModality,
    ClaimPolarity,
    ClaimType,
    EntityType,
    ImpactArea,
    InsightType,
    MaturityStage,
    ObjectType,
    ProcessingStatus,
    RadarRecommendation,
    RelationDirection,
    RelationType,
    ReportType,
    SignalType,
    SourceType,
    TechnologyCategory,
    TrendDirection,
    DetailSectionType,
)


class ObjectRef(PrimitiveModel):
    object_type: ObjectType | str
    object_id: str
    label: str | None = None

    @field_validator("object_type")
    @classmethod
    def _coerce_object_type(cls, value: ObjectType | str) -> ObjectType:
        return ObjectType(value)

    @field_validator("object_id")
    @classmethod
    def _validate_object_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("object_id is required")
        return text


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


class Entity(PrimitiveModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    normalized_key: str
    description: str | None = None
    url: str | None = None
    source_signal_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_id", "canonical_name", "normalized_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("entity fields must be non-empty")
        return text


class Topic(PrimitiveModel):
    topic_id: str
    name: str
    normalized_key: str
    parent_topic_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    description: str | None = None
    confidence: Confidence

    @field_validator("topic_id", "name", "normalized_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("topic fields must be non-empty")
        return text


class Technology(PrimitiveModel):
    technology_id: str
    name: str
    normalized_key: str
    category: TechnologyCategory
    subcategory: str | None = None
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    description: str | None = None
    first_seen_signal_id: str | None = None
    confidence: Confidence
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("technology_id", "name", "normalized_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("technology fields must be non-empty")
        return text


class Claim(PrimitiveModel):
    claim_id: str
    signal_id: str
    claim_type: ClaimType
    text: str
    subject_ref: ObjectRef | None = None
    predicate: str | None = None
    object_ref: ObjectRef | None = None
    polarity: ClaimPolarity = ClaimPolarity.NEUTRAL
    modality: ClaimModality = ClaimModality.ASSERTED
    evidence_span: TextSpan | None = None
    confidence: Confidence

    @field_validator("claim_id", "signal_id", "text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("claim fields must be non-empty")
        return text


class Relation(PrimitiveModel):
    relation_id: str
    relation_type: RelationType
    source_ref: ObjectRef
    target_ref: ObjectRef
    direction: RelationDirection = RelationDirection.DIRECTED
    evidence_signal_ids: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relation_id")
    @classmethod
    def _validate_relation_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("relation_id is required")
        return text

    @field_validator("evidence_signal_ids", "evidence_claim_ids", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "Relation":
        if not self.evidence_signal_ids and not self.evidence_claim_ids:
            raise ValueError("relation requires evidence_signal_ids or evidence_claim_ids")
        if self.relation_type in {RelationType.IMPLEMENTS, RelationType.PROPOSES, RelationType.ADOPTS} and self.direction != RelationDirection.DIRECTED:
            raise ValueError(f"{self.relation_type.value} relation must be directed")
        if self.relation_type in {RelationType.COMPARES, RelationType.SIMILAR_TO} and self.direction != RelationDirection.UNDIRECTED:
            raise ValueError(f"{self.relation_type.value} relation must be undirected")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self


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


class DetailSection(PrimitiveModel):
    title: str
    section_type: DetailSectionType
    content: str | None = None
    cards: list[BoardCard] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    metrics: list[DisplayMetric] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class DetailPage(PrimitiveModel):
    page_id: str
    board_type: BoardType
    title: str
    summary: str
    primary_object_ref: ObjectRef
    sections: list[DetailSection] = Field(default_factory=list)
    related_cards: list[BoardCard] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
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


def make_object_ref(object_type: ObjectType | str, object_id: str, *, label: str | None = None) -> ObjectRef:
    return ObjectRef(object_type=object_type, object_id=object_id, label=label)


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
