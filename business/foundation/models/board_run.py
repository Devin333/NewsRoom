from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation._models import BoardCard, DetailPage, Insight, Report
from business.foundation.artifacts import BusinessArtifactRef
from business.foundation.evidence import BusinessEvidenceRef
from business.foundation.memory_refs import BusinessMemoryRef
from business.foundation.primitives import PrimitiveModel, SourceRef
from business.foundation.taxonomy import BoardType
from business.foundation.models.quality_loop import (
    BusinessFeedbackEvent,
    BusinessPolicySnapshot,
    BusinessQualitySnapshot,
)


class BoardRunResult(PrimitiveModel):
    board_type: BoardType
    run_id: str
    cards: list[BoardCard] = Field(default_factory=list)
    detail_pages: list[DetailPage] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    reports: list[Report] = Field(default_factory=list)
    board_output: dict[str, Any] = Field(default_factory=dict)
    policy_snapshot: BusinessPolicySnapshot | None = None
    quality_summary: BusinessQualitySnapshot | None = None
    feedback_candidates: list[BusinessFeedbackEvent] = Field(default_factory=list)
    trace_ref: SourceRef | None = None
    manifest_ref: SourceRef | None = None
    artifact_refs: list[BusinessArtifactRef] = Field(default_factory=list)
    evidence_refs: list[BusinessEvidenceRef] = Field(default_factory=list)
    memory_refs: list[BusinessMemoryRef] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


__all__ = ["BoardRunResult"]
