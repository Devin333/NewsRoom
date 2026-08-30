from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel
from backend.research.domain.common import EvidenceRef, SourceLineage, require_text, unique_texts


class ResearchClaim(PrimitiveModel):
    claim_id: str
    text: str
    claim_type: Literal["problem", "method", "experiment", "limitation", "sota", "reproducibility", "other"] = "other"
    section_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim_id", "text")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "claim fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("claim confidence must be between 0 and 1")
        return numeric

    @field_validator("evidence_ids")
    @classmethod
    def _unique_evidence_ids(cls, value: list[str]) -> list[str]:
        return unique_texts(value)


class ResearchEvidenceItem(PrimitiveModel):
    evidence_id: str
    paper_id: str
    title: str
    summary: str
    evidence_type: str
    source_ref: str
    span_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    lineage: SourceLineage
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id", "paper_id", "title", "summary", "evidence_type", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "evidence item fields")

    @model_validator(mode="after")
    def _normalize_refs(self) -> "ResearchEvidenceItem":
        self.lineage.require_refs("evidence item requires source lineage")
        object.__setattr__(self, "span_refs", unique_texts(self.span_refs))
        object.__setattr__(self, "claim_refs", unique_texts(self.claim_refs))
        return self

    def as_ref(self) -> EvidenceRef:
        return EvidenceRef(
            evidence_id=self.evidence_id,
            source_ref=self.source_ref,
            span_ref=self.span_refs[0] if self.span_refs else None,
            confidence=self.confidence,
        )


class ResearchEvidencePack(PrimitiveModel):
    pack_id: str
    paper_id: str
    items: list[ResearchEvidenceItem] = Field(default_factory=list)
    coverage: dict[str, float] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    lineage: SourceLineage
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pack_id", "paper_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "evidence pack fields")

    @model_validator(mode="after")
    def _normalize(self) -> "ResearchEvidencePack":
        self.lineage.require_refs("evidence pack requires source lineage")
        object.__setattr__(self, "missing_information", unique_texts(self.missing_information))
        normalized_coverage: dict[str, float] = {}
        for key, value in self.coverage.items():
            numeric = float(value)
            if numeric < 0.0 or numeric > 1.0:
                raise ValueError("coverage values must be between 0 and 1")
            normalized_coverage[str(key)] = numeric
        object.__setattr__(self, "coverage", normalized_coverage)
        return self

    @property
    def evidence_ids(self) -> list[str]:
        return [item.evidence_id for item in self.items]


__all__ = ["ResearchClaim", "ResearchEvidenceItem", "ResearchEvidencePack"]
