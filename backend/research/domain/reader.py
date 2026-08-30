from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel
from backend.research.domain.analysis import ResearchAnalysis
from backend.research.domain.common import QualityFlag, SourceLineage, require_text, unique_texts
from backend.research.domain.document import ResearchDocument
from backend.research.domain.evidence import ResearchEvidencePack
from backend.research.domain.paper import ResearchPaper


ReaderPayloadStatus: TypeAlias = Literal["pending", "ready", "needs_repair", "failed"]


class ReaderNavigationItem(PrimitiveModel):
    item_id: str
    title: str
    target_ref: str
    level: int = 1
    order: int = 0

    @field_validator("item_id", "title", "target_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "navigation item fields")


class ReaderAnnotation(PrimitiveModel):
    annotation_id: str
    target_ref: str
    annotation_type: Literal["summary", "warning", "definition", "question", "note"] = "note"
    text: str
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("annotation_id", "target_ref", "text")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "annotation fields")

    @field_validator("source_refs")
    @classmethod
    def _unique_source_refs(cls, value: list[str]) -> list[str]:
        return unique_texts(value)


class ResearchReaderPayload(PrimitiveModel):
    payload_id: str
    paper: ResearchPaper
    document: ResearchDocument
    analysis: ResearchAnalysis | None = None
    evidence: ResearchEvidencePack | None = None
    navigation: list[ReaderNavigationItem] = Field(default_factory=list)
    annotations: list[ReaderAnnotation] = Field(default_factory=list)
    source_lineage: SourceLineage
    quality: list[QualityFlag] = Field(default_factory=list)
    status: ReaderPayloadStatus = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload_id")
    @classmethod
    def _required_payload_id(cls, value: str) -> str:
        return require_text(value, "reader payload id")

    @model_validator(mode="after")
    def _validate_payload(self) -> "ResearchReaderPayload":
        if self.paper.paper_id != self.document.paper_id:
            raise ValueError("reader payload paper and document must reference the same paper")
        if self.analysis is not None and self.analysis.paper_id != self.paper.paper_id:
            raise ValueError("reader payload analysis must reference the same paper")
        if self.evidence is not None and self.evidence.paper_id != self.paper.paper_id:
            raise ValueError("reader payload evidence must reference the same paper")
        self.source_lineage.require_refs("reader payload requires source lineage")
        return self


__all__ = ["ReaderAnnotation", "ReaderNavigationItem", "ReaderPayloadStatus", "ResearchReaderPayload"]
