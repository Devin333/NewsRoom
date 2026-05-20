from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import (
    Claim,
    Confidence,
    Entity,
    ObjectRef,
    PrimitiveModel,
    TaxonomyType,
    Technology,
    Topic,
)


class TaxonomyAssignment(PrimitiveModel):
    object_ref: ObjectRef
    taxonomy_type: TaxonomyType
    category: str
    subcategory: str | None = None
    confidence: Confidence
    evidence_text: str | None = None


class ExtractionWarning(PrimitiveModel):
    signal_id: str
    warning_type: str
    message: str


class ExtractionResult(PrimitiveModel):
    signal_id: str
    entities: list[Entity] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    technologies: list[Technology] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    taxonomy_assignments: list[TaxonomyAssignment] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
