from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel, normalize_key
from business.research.domain.common import CandidateStatus, require_text, unique_texts


TaxonomyLevel = Literal["domain", "area", "task"]


class TaxonomyTerm(PrimitiveModel):
    term_id: str
    level: TaxonomyLevel
    label: str
    description: str | None = None
    parent_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def _required_label(cls, value: str) -> str:
        return require_text(value, "taxonomy label")

    @model_validator(mode="after")
    def _normalize(self) -> "TaxonomyTerm":
        object.__setattr__(self, "term_id", self.term_id or normalize_key(self.label))
        object.__setattr__(self, "parent_ids", unique_texts(self.parent_ids))
        if not self.term_id:
            raise ValueError("taxonomy term id is required")
        return self


class TaxonomyCandidate(PrimitiveModel):
    candidate_id: str
    level: TaxonomyLevel
    term_id: str
    label: str
    evidence_refs: list[str]
    confidence: float = 0.0
    status: CandidateStatus = CandidateStatus.CANDIDATE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_id", "term_id", "label")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "taxonomy candidate fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("taxonomy candidate confidence must be between 0 and 1")
        return numeric

    @field_validator("evidence_refs")
    @classmethod
    def _require_evidence_refs(cls, value: list[str]) -> list[str]:
        refs = unique_texts(value)
        if not refs:
            raise ValueError("taxonomy candidate requires evidence refs")
        return refs


class TaxonomyAssignment(PrimitiveModel):
    paper_id: str
    domains: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    accepted_candidate_ids: list[str] = Field(default_factory=list)
    review_candidate_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id")
    @classmethod
    def _required_paper_id(cls, value: str) -> str:
        return require_text(value, "paper id")

    @model_validator(mode="after")
    def _normalize_lists(self) -> "TaxonomyAssignment":
        for field_name in ("domains", "areas", "tasks", "accepted_candidate_ids", "review_candidate_ids"):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        return self


__all__ = ["TaxonomyAssignment", "TaxonomyCandidate", "TaxonomyLevel", "TaxonomyTerm"]
