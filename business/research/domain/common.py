from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel, build_stable_id, normalize_key


class ResearchValidationSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceRef(PrimitiveModel):
    evidence_id: str
    source_ref: str
    section_id: str | None = None
    claim_id: str | None = None
    span_ref: str | None = None
    quote: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "evidence reference fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return bounded_float(value, "confidence")


class SourceLineage(PrimitiveModel):
    source_refs: list[str] = Field(default_factory=list)
    source_hash: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    collected_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_refs(self) -> "SourceLineage":
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        object.__setattr__(self, "artifact_refs", unique_texts(self.artifact_refs))
        if self.collected_at is not None:
            object.__setattr__(self, "collected_at", ensure_utc(self.collected_at))
        return self

    def require_refs(self, reason: str = "source lineage requires at least one source ref") -> "SourceLineage":
        if not self.source_refs:
            raise ValueError(reason)
        return self


class QualityFlag(PrimitiveModel):
    flag_type: str
    severity: ResearchValidationSeverity = ResearchValidationSeverity.MEDIUM
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("flag_type", "message")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "quality flag fields")

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence_refs(cls, value: list[str]) -> list[str]:
        return unique_texts(value)


class GateResult(PrimitiveModel):
    gate_name: str
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("gate_name")
    @classmethod
    def _required_gate(cls, value: str) -> str:
        return require_text(value, "gate name")

    @classmethod
    def pass_(cls, gate_name: str, *, metadata: dict[str, Any] | None = None) -> "GateResult":
        return cls(gate_name=gate_name, passed=True, metadata=metadata or {})

    @classmethod
    def fail(
        cls,
        gate_name: str,
        reason: str,
        *,
        severity: ResearchValidationSeverity = ResearchValidationSeverity.HIGH,
        metadata: dict[str, Any] | None = None,
    ) -> "GateResult":
        return cls(
            gate_name=gate_name,
            passed=False,
            reasons=[reason],
            quality_flags=[
                QualityFlag(
                    flag_type=normalize_key(gate_name) or "gate_failure",
                    severity=severity,
                    message=reason,
                )
            ],
            metadata=metadata or {},
        )


class CandidateStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class CandidateReview(PrimitiveModel):
    candidate_id: str
    status: CandidateStatus = CandidateStatus.CANDIDATE
    reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_id")
    @classmethod
    def _required_candidate_id(cls, value: str) -> str:
        return require_text(value, "candidate id")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return bounded_float(value, "confidence")

    @model_validator(mode="after")
    def _normalize_refs(self) -> "CandidateReview":
        object.__setattr__(self, "reasons", unique_texts(self.reasons))
        object.__setattr__(self, "evidence_refs", unique_texts(self.evidence_refs))
        return self


class SourceScopedValue(PrimitiveModel):
    value: str
    source_refs: list[str]
    status: Literal["candidate", "verified"] = "candidate"
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("value")
    @classmethod
    def _required_value(cls, value: str) -> str:
        return require_text(value, "source scoped value")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return bounded_float(value, "confidence")

    @model_validator(mode="after")
    def _require_source_refs(self) -> "SourceScopedValue":
        refs = unique_texts(self.source_refs)
        if not refs:
            raise ValueError("source scoped value requires source refs")
        object.__setattr__(self, "source_refs", refs)
        return self


def stable_research_id(prefix: str, *parts: Any) -> str:
    return build_stable_id(prefix, *parts)


def require_text(value: Any, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def unique_texts(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def bounded_float(value: float, label: str, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    numeric = float(value)
    if numeric < minimum or numeric > maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}")
    return numeric


def non_negative_int(value: int, label: str) -> int:
    numeric = int(value)
    if numeric < 0:
        raise ValueError(f"{label} must be non-negative")
    return numeric


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CandidateReview",
    "CandidateStatus",
    "EvidenceRef",
    "GateResult",
    "QualityFlag",
    "ResearchValidationSeverity",
    "SourceLineage",
    "SourceScopedValue",
    "bounded_float",
    "ensure_utc",
    "non_negative_int",
    "optional_text",
    "require_text",
    "stable_research_id",
    "unique_texts",
]
