from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel
from business.research.domain.common import SourceLineage, require_text, unique_texts


ReaderIssueType = Literal[
    "image_missing_or_broken",
    "figure_caption_mismatch",
    "latex_source_rendered",
    "formula_placeholder_missing",
    "table_parse_error",
    "section_boundary_error",
    "citation_link_error",
    "reference_parse_error",
    "source_lineage_missing",
    "reader_payload_schema_error",
]


class ReaderIssue(PrimitiveModel):
    issue_id: str
    paper_id: str
    run_id: str | None = None
    step_id: str | None = None
    issue_type: ReaderIssueType
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    error_signature: str
    symptom: str
    source_refs: list[str] = Field(default_factory=list)
    payload_ref: str | None = None
    detector_evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("issue_id", "paper_id", "error_signature", "symptom")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "reader issue fields")

    @model_validator(mode="after")
    def _normalize_refs(self) -> "ReaderIssue":
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        object.__setattr__(self, "detector_evidence", unique_texts(self.detector_evidence))
        return self


class ReaderRepairCase(PrimitiveModel):
    repair_case_id: str
    issue: ReaderIssue
    repair_strategy: str
    successful: bool
    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    payload_before_ref: str
    payload_after_ref: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repair_case_id", "repair_strategy", "payload_before_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair case fields")

    @model_validator(mode="after")
    def _normalize_refs(self) -> "ReaderRepairCase":
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        object.__setattr__(self, "constraints", unique_texts(self.constraints))
        if self.successful and not self.payload_after_ref:
            raise ValueError("successful repair case requires payload_after_ref")
        return self


class ReaderRepairStrategy(PrimitiveModel):
    strategy_id: str
    issue_type: ReaderIssueType
    applicability: str
    steps: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    known_failures: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source_case_refs: list[str] = Field(default_factory=list)
    status: Literal["candidate", "validated", "deprecated"] = "candidate"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("strategy_id", "applicability")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair strategy fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("repair strategy confidence must be between 0 and 1")
        return numeric

    @model_validator(mode="after")
    def _normalize_lists(self) -> "ReaderRepairStrategy":
        object.__setattr__(self, "steps", unique_texts(self.steps))
        object.__setattr__(self, "constraints", unique_texts(self.constraints))
        object.__setattr__(self, "known_failures", unique_texts(self.known_failures))
        object.__setattr__(self, "source_case_refs", unique_texts(self.source_case_refs))
        if not self.steps:
            raise ValueError("repair strategy requires steps")
        return self


class ReaderRepairContextPack(PrimitiveModel):
    context_id: str
    issue: ReaderIssue
    recalled_cases: list[ReaderRepairCase] = Field(default_factory=list)
    candidate_strategies: list[ReaderRepairStrategy] = Field(default_factory=list)
    source_lineage: SourceLineage
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("context_id")
    @classmethod
    def _required_context_id(cls, value: str) -> str:
        return require_text(value, "repair context id")

    @model_validator(mode="after")
    def _require_lineage(self) -> "ReaderRepairContextPack":
        self.source_lineage.require_refs("reader repair context requires source lineage")
        return self


__all__ = ["ReaderIssue", "ReaderIssueType", "ReaderRepairCase", "ReaderRepairContextPack", "ReaderRepairStrategy"]
