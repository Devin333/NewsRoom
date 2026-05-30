from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CitationFailureCategory:
    code: str
    count: int
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "count": self.count,
            "items": list(self.items),
        }


@dataclass(frozen=True)
class CitationSectionResult:
    section_id: str
    section_title: str
    cited_urls: list[str] = field(default_factory=list)
    cited_evidence_ids: list[str] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    issue_details: dict[str, list[str]] = field(default_factory=dict)
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_title": self.section_title,
            "cited_urls": list(self.cited_urls),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "issue_codes": list(self.issue_codes),
            "issue_details": {
                key: list(value) for key, value in self.issue_details.items()
            },
            "passed": self.passed,
        }


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
    unknown_urls_count: int = 0
    unsupported_evidence_ids_count: int = 0
    citation_failure_category_count: int = 0
    citation_failure_categories: list[str] = field(default_factory=list)

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
            "unknown_urls_count": self.unknown_urls_count,
            "unsupported_evidence_ids_count": self.unsupported_evidence_ids_count,
            "citation_failure_category_count": self.citation_failure_category_count,
            "citation_failure_categories": list(self.citation_failure_categories),
        }


@dataclass(frozen=True)
class QualityResult:
    decision: str
    passed: bool
    route: str
    blocked: bool
    quality_score: float | None = None
    citation_coverage_score: float | None = None
    claim_support_score: float | None = None
    section_source_coverage_score: float | None = None
    support_coverage: float | None = None
    evidence_alignment_score: float | None = None
    rewrite_attempts: int = 0
    rewrite_required: bool = False
    human_review_required: bool = False
    route_history: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    artifact_refs: dict[str, Any] = field(default_factory=dict)
    citation_check_result: Any | None = None
    editor_review: Any | None = None
    support_matrix: Any | None = None
    report_quality_summary: Any | None = None
    quality_gate_metrics: Any | None = None
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "passed": self.passed,
            "route": self.route,
            "blocked": self.blocked,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "claim_support_score": self.claim_support_score,
            "section_source_coverage_score": self.section_source_coverage_score,
            "support_coverage": self.support_coverage,
            "evidence_alignment_score": self.evidence_alignment_score,
            "rewrite_attempts": self.rewrite_attempts,
            "rewrite_required": self.rewrite_required,
            "human_review_required": self.human_review_required,
            "route_history": list(self.route_history),
            "reasons": list(self.reasons),
            "artifact_refs": {
                key: _artifact_ref(value) for key, value in self.artifact_refs.items()
            },
            "citation_check_result": _artifact_ref(self.citation_check_result),
            "editor_review": _artifact_ref(self.editor_review),
            "support_matrix": _artifact_ref(self.support_matrix),
            "report_quality_summary": _artifact_ref(self.report_quality_summary),
            "quality_gate_metrics": _artifact_ref(self.quality_gate_metrics),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BlockedReport:
    title: str
    blocked_reason: str
    unsupported_claims: list[Any] = field(default_factory=list)
    quality_score: float | None = None
    next_actions: list[str] = field(default_factory=list)
    status: str = "blocked"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "blocked_reason": self.blocked_reason,
            "unsupported_claims": [
                claim.to_dict() if hasattr(claim, "to_dict") else claim
                for claim in self.unsupported_claims
            ],
            "quality_score": self.quality_score,
            "next_actions": list(self.next_actions),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HumanReviewRequest:
    review_id: str
    run_id: str
    reason: str
    risk_level: str
    report_id: str | None = None
    draft_id: str | None = None
    review_reason: str | None = None
    claims_to_review: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[Any] = field(default_factory=list)
    suggested_decision: str | None = None
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
            "review_reason": self.review_reason or self.reason,
            "risk_level": self.risk_level,
            "claims_to_review": [dict(claim) for claim in self.claims_to_review],
            "evidence_refs": [_artifact_ref(ref) for ref in self.evidence_refs],
            "suggested_decision": self.suggested_decision,
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

    def __post_init__(self) -> None:
        allowed = {"approve", "reject", "request_rewrite", "edit_required"}
        if self.decision not in allowed:
            raise ValueError(f"unsupported human review decision: {self.decision}")

    def to_quality_result(self, *, base_result: QualityResult | None = None) -> QualityResult:
        if self.decision == "approve":
            decision = "pass"
            route = "final"
            passed = True
            blocked = False
            rewrite_required = False
        elif self.decision == "request_rewrite" or self.decision == "edit_required":
            decision = "rewrite_required"
            route = "rewrite"
            passed = False
            blocked = False
            rewrite_required = True
        else:
            decision = "blocked"
            route = "blocked"
            passed = False
            blocked = True
            rewrite_required = False
        return QualityResult(
            decision=decision,
            passed=passed,
            route=route,
            blocked=blocked,
            quality_score=base_result.quality_score if base_result else None,
            citation_coverage_score=base_result.citation_coverage_score if base_result else None,
            claim_support_score=base_result.claim_support_score if base_result else None,
            section_source_coverage_score=(
                base_result.section_source_coverage_score if base_result else None
            ),
            support_coverage=base_result.support_coverage if base_result else None,
            evidence_alignment_score=base_result.evidence_alignment_score if base_result else None,
            rewrite_attempts=base_result.rewrite_attempts if base_result else 0,
            rewrite_required=rewrite_required,
            human_review_required=False,
            route_history=[
                *(base_result.route_history if base_result else []),
                "human_review",
                route,
            ],
            reasons=[f"human review decision: {self.decision}"],
            artifact_refs=base_result.artifact_refs if base_result else {},
            citation_check_result=base_result.citation_check_result if base_result else None,
            editor_review=base_result.editor_review if base_result else None,
            support_matrix=base_result.support_matrix if base_result else None,
            report_quality_summary=base_result.report_quality_summary if base_result else None,
            quality_gate_metrics=base_result.quality_gate_metrics if base_result else None,
            metadata={
                **(base_result.metadata if base_result else {}),
                "human_review_id": self.review_id,
                "human_review_decision": self.decision,
                "reviewer_id": self.reviewer_id,
                "review_notes": self.notes,
            },
        )

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
    expected_decision: str | None = None
    actual_decision: str | None = None
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
            "expected_decision": self.expected_decision,
            "actual_decision": self.actual_decision,
            "differences": list(self.differences),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }


def _artifact_ref(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
