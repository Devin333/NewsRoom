from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel
from business.research.domain.common import SourceLineage, require_text, unique_texts
from business.research.domain.evidence import ResearchEvidenceItem


class ResearchRetrievalGoal(PrimitiveModel):
    goal_id: str
    paper_id: str
    question: str
    required_evidence_types: list[str]
    target_sections: list[str] = Field(default_factory=list)
    target_claims: list[str] = Field(default_factory=list)
    allowed_source_refs: list[str]
    allowed_memory_namespaces: list[str]
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("goal_id", "paper_id", "question")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "retrieval goal fields")

    @model_validator(mode="after")
    def _require_scope(self) -> "ResearchRetrievalGoal":
        for field_name in (
            "required_evidence_types",
            "target_sections",
            "target_claims",
            "allowed_source_refs",
            "allowed_memory_namespaces",
        ):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        if not self.required_evidence_types:
            raise ValueError("research retrieval goal requires evidence types")
        if not self.allowed_source_refs:
            raise ValueError("research retrieval goal requires allowed source refs")
        if not self.allowed_memory_namespaces:
            raise ValueError("research retrieval goal requires allowed memory namespaces")
        return self


class ResearchRAGGapReport(PrimitiveModel):
    missing_information: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    rejected_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> "ResearchRAGGapReport":
        for field_name in ("missing_information", "conflicting_evidence", "rejected_reasons"):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        return self


class ResearchRAGContext(PrimitiveModel):
    context_id: str
    paper_id: str
    goal: ResearchRetrievalGoal
    accepted_evidence: list[ResearchEvidenceItem] = Field(default_factory=list)
    rejected_evidence: list[ResearchEvidenceItem] = Field(default_factory=list)
    conflicting_evidence: list[ResearchEvidenceItem] = Field(default_factory=list)
    memory_context: list[dict[str, Any]] = Field(default_factory=list)
    gap_report: ResearchRAGGapReport = Field(default_factory=ResearchRAGGapReport)
    source_refs: list[str]
    lineage: SourceLineage
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("context_id", "paper_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "RAG context fields")

    @model_validator(mode="after")
    def _validate_scope(self) -> "ResearchRAGContext":
        if self.goal.paper_id != self.paper_id:
            raise ValueError("RAG context goal must reference the same paper")
        self.lineage.require_refs("RAG context requires source lineage")
        refs = unique_texts(self.source_refs)
        if not refs:
            raise ValueError("RAG context requires source refs")
        allowed = set(self.goal.allowed_source_refs)
        outside = sorted(ref for ref in refs if ref not in allowed)
        if outside:
            raise ValueError(f"RAG context source refs outside allowed scope: {outside}")
        object.__setattr__(self, "source_refs", refs)
        return self


__all__ = ["ResearchRAGContext", "ResearchRAGGapReport", "ResearchRetrievalGoal"]
