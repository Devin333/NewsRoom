from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class QualityEvent:
    event_type: str
    occurred_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class QualityGateMetrics:
    evidence_items_count: int
    unsupported_urls_count: int
    missing_section_sources_count: int
    unsupported_sections_count: int
    blocked: bool
    decision: str
    citation_coverage_score: float
    support_coverage: float
    quality_score: float
    accepted_claims_count: int = 0
    rejected_claims_count: int = 0
    uncertain_claims_count: int = 0
    unsupported_claims_count: int = 0
    rejected_claim_usage_count: int = 0
    claim_support_score: float = 0.0
    section_source_coverage_score: float = 0.0
    rewrite_attempts: int = 0
    rewrite_required: bool = False
    human_review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_items_count": self.evidence_items_count,
            "unsupported_urls_count": self.unsupported_urls_count,
            "missing_section_sources_count": self.missing_section_sources_count,
            "unsupported_sections_count": self.unsupported_sections_count,
            "blocked": self.blocked,
            "decision": self.decision,
            "citation_coverage_score": self.citation_coverage_score,
            "support_coverage": self.support_coverage,
            "quality_score": self.quality_score,
            "accepted_claims_count": self.accepted_claims_count,
            "rejected_claims_count": self.rejected_claims_count,
            "uncertain_claims_count": self.uncertain_claims_count,
            "unsupported_claims_count": self.unsupported_claims_count,
            "rejected_claim_usage_count": self.rejected_claim_usage_count,
            "claim_support_score": self.claim_support_score,
            "section_source_coverage_score": self.section_source_coverage_score,
            "rewrite_attempts": self.rewrite_attempts,
            "rewrite_required": self.rewrite_required,
            "human_review_required": self.human_review_required,
        }


@dataclass(frozen=True)
class HumanReviewRequest:
    review_id: str
    run_id: str
    reason: str
    risk_level: str
    report_id: str | None = None
    draft_id: str | None = None
    evidence_bundle_ref: Any | None = None
    quality_artifact_refs: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "run_id": self.run_id,
            "report_id": self.report_id,
            "draft_id": self.draft_id,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "evidence_bundle_ref": _artifact_ref(self.evidence_bundle_ref),
            "quality_artifact_refs": {
                key: _artifact_ref(value) for key, value in self.quality_artifact_refs.items()
            },
            "status": self.status,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HumanReviewDecision:
    review_id: str
    decision: str
    reviewer_id: str | None = None
    notes: str | None = None
    decided_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "decision": self.decision,
            "reviewer_id": self.reviewer_id,
            "notes": self.notes,
            "decided_at": self.decided_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class QualityEvalCase:
    case_id: str
    request: dict[str, Any]
    evidence_bundle: Any
    report_draft: dict[str, Any]
    expected_decision: str | None = None
    expected_unsupported_claims: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "request": dict(self.request),
            "evidence_bundle": (
                self.evidence_bundle.to_dict()
                if hasattr(self.evidence_bundle, "to_dict")
                else self.evidence_bundle
            ),
            "report_draft": dict(self.report_draft),
            "expected_decision": self.expected_decision,
            "expected_unsupported_claims": list(self.expected_unsupported_claims),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class QualityEvalRecord:
    eval_id: str
    case_id: str
    citation_check_result: Any
    editor_review: Any
    quality_summary: Any
    passed: bool
    differences: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_id": self.eval_id,
            "case_id": self.case_id,
            "citation_check_result": _artifact_ref(self.citation_check_result),
            "editor_review": _artifact_ref(self.editor_review),
            "quality_summary": _artifact_ref(self.quality_summary),
            "passed": self.passed,
            "differences": list(self.differences),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }


def _artifact_ref(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
