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


class BoardRunPipelineSnapshot(PrimitiveModel):
    schema_version: str = "business.board.run.pipeline_snapshot.v1"
    extraction_count: int = 0
    processed_relations: list[dict[str, Any]] = Field(default_factory=list)
    rejected_relations: list[dict[str, Any]] = Field(default_factory=list)
    analysis: dict[str, Any] = Field(default_factory=dict)

    def legacy_fields(self) -> dict[str, Any]:
        return {
            "processed_relations": [dict(item) for item in self.processed_relations],
            "rejected_relations": [dict(item) for item in self.rejected_relations],
            "analysis": dict(self.analysis),
        }


class BoardRunResult(PrimitiveModel):
    board_type: BoardType
    run_id: str
    cards: list[BoardCard] = Field(default_factory=list)
    detail_pages: list[DetailPage] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    reports: list[Report] = Field(default_factory=list)
    board_output: dict[str, Any] = Field(default_factory=dict)
    report_payloads: list[dict[str, Any]] = Field(default_factory=list)
    pipeline_snapshot: BoardRunPipelineSnapshot | None = None
    policy_snapshot: BusinessPolicySnapshot | None = None
    quality_summary: BusinessQualitySnapshot | None = None
    feedback_candidates: list[BusinessFeedbackEvent] = Field(default_factory=list)
    trace_ref: SourceRef | None = None
    manifest_ref: SourceRef | None = None
    artifact_refs: list[BusinessArtifactRef] = Field(default_factory=list)
    evidence_refs: list[BusinessEvidenceRef] = Field(default_factory=list)
    memory_refs: list[BusinessMemoryRef] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


__all__ = ["BoardRunPipelineSnapshot", "BoardRunResult"]
