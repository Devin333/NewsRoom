from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel
from business.research.domain.common import EvidenceRef, QualityFlag, require_text, unique_texts
from business.research.domain.evidence import ResearchClaim


class ThreeMinuteRead(PrimitiveModel):
    problem: str
    core_idea: str
    key_contributions: list[str] = Field(default_factory=list)
    method_summary: str = ""
    experiment_summary: str = ""
    limitations: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    read_next: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = 0.0
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("problem", "core_idea")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "three minute read fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("three minute read confidence must be between 0 and 1")
        return numeric

    @model_validator(mode="after")
    def _normalize_lists(self) -> "ThreeMinuteRead":
        object.__setattr__(self, "key_contributions", unique_texts(self.key_contributions))
        object.__setattr__(self, "limitations", unique_texts(self.limitations))
        object.__setattr__(self, "read_next", unique_texts(self.read_next))
        return self

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence_refs)


class ResearchAnalysis(PrimitiveModel):
    paper_id: str
    summary: ThreeMinuteRead
    contributions: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    experiments: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reproducibility: list[str] = Field(default_factory=list)
    related_work: list[str] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)
    evidence_pack_id: str
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id", "evidence_pack_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "analysis fields")

    @model_validator(mode="after")
    def _normalize_lists(self) -> "ResearchAnalysis":
        for field_name in (
            "contributions",
            "methods",
            "experiments",
            "limitations",
            "reproducibility",
            "related_work",
        ):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        return self


__all__ = ["ResearchAnalysis", "ThreeMinuteRead"]
