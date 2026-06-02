from __future__ import annotations

from typing import Any

from business.layers.relation.evidence import EvidenceBundle, VerifiedFindings
from business.layers.analysis.quality import (
    EditorDecision,
    HumanReviewRequest,
    QualityGateMetrics,
    QualityResult,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_observability import (
    quality_gate_observability_metrics,
)


def human_review_request(
    *,
    evidence_bundle: EvidenceBundle,
    review: Any,
    quality_summary: Any,
) -> HumanReviewRequest | None:
    if review.decision == EditorDecision.PASS and quality_summary.quality_score >= 0.8:
        return None
    risk_level = "critical" if review.decision == EditorDecision.BLOCKED else "medium"
    reason = "quality gate blocked" if review.decision == EditorDecision.BLOCKED else "quality gate rewrite required"
    return HumanReviewRequest(
        review_id=f"review-{evidence_bundle.bundle_id}",
        run_id=evidence_bundle.bundle_id,
        draft_id=f"draft-{evidence_bundle.bundle_id}",
        reason=reason,
        risk_level=risk_level,
        quality_artifact_refs={
            "citation_check_result": "citation_check_result.json",
            "editor_review": "editor_review.json",
            "report_quality_summary": "report_quality_summary.json",
        },
        metadata={
            "decision": review.decision.value,
            "quality_score": quality_summary.quality_score,
            "reason_count": len(review.reasons),
        },
    )


def quality_gate_metrics(
    *,
    evidence_bundle: EvidenceBundle,
    verified_findings: VerifiedFindings,
    citation_check: Any,
    support_matrix: Any,
    quality_summary: Any,
    review: Any,
    rewrite_attempts: int,
    human_review_required: bool,
    memory_quality_result: Any | None = None,
) -> QualityGateMetrics:
    blocked = review.decision != EditorDecision.PASS
    rewrite_required = review.decision == EditorDecision.REWRITE_REQUIRED
    return QualityGateMetrics(
        evidence_items_count=len(evidence_bundle.items),
        unsupported_urls_count=len(citation_check.unknown_urls) + len(citation_check.unsupported_urls),
        missing_section_sources_count=len(citation_check.missing_section_sources),
        unsupported_sections_count=len(support_matrix.unsupported_sections),
        blocked=blocked,
        decision=review.decision.value,
        citation_coverage_score=citation_check.citation_coverage_score,
        support_coverage=quality_summary.support_coverage,
        quality_score=quality_summary.quality_score,
        accepted_claims_count=len(verified_findings.accepted_claims),
        rejected_claims_count=len(verified_findings.rejected_claims),
        uncertain_claims_count=len(verified_findings.uncertain_claims),
        unsupported_claims_count=len(citation_check.unsupported_claims),
        rejected_claim_usage_count=len(citation_check.rejected_claim_usage),
        claim_support_score=citation_check.claim_support_score,
        section_source_coverage_score=citation_check.section_source_coverage_score,
        rewrite_attempts=rewrite_attempts,
        rewrite_required=rewrite_required,
        human_review_required=human_review_required,
        unknown_urls_count=len(citation_check.unknown_urls),
        unsupported_evidence_ids_count=len(citation_check.unsupported_evidence_ids),
        citation_failure_category_count=len(citation_check.failure_categories),
        citation_failure_categories=[
            category.code for category in citation_check.failure_categories
        ],
        **quality_gate_observability_metrics(
            blocked=blocked,
            rewrite_required=rewrite_required,
            human_review_required=human_review_required,
            memory_quality_result=memory_quality_result,
        ),
    )


def quality_route(
    *,
    review: Any,
    rewrite_attempts: int,
    human_review_required: bool,
) -> str:
    if human_review_required:
        return "human_review"
    if review.decision == EditorDecision.BLOCKED:
        return "blocked"
    if rewrite_attempts > 0 or review.decision == EditorDecision.REWRITE_REQUIRED:
        return "rewrite"
    return "final"


def quality_result(
    *,
    citation_check: Any,
    support_matrix: Any,
    quality_summary: Any,
    review: Any,
    quality_gate_metrics: Any,
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
) -> QualityResult:
    return QualityResult(
        decision=review.decision.value,
        passed=review.decision == EditorDecision.PASS,
        route=route,
        blocked=review.decision != EditorDecision.PASS,
        quality_score=quality_summary.quality_score,
        citation_coverage_score=citation_check.citation_coverage_score,
        claim_support_score=citation_check.claim_support_score,
        section_source_coverage_score=citation_check.section_source_coverage_score,
        support_coverage=quality_summary.support_coverage,
        evidence_alignment_score=quality_summary.evidence_alignment_score,
        rewrite_attempts=rewrite_attempts,
        rewrite_required=review.decision == EditorDecision.REWRITE_REQUIRED,
        human_review_required=human_review_required,
        route_history=_quality_route_history(
            route=route,
            review=review,
            rewrite_attempts=rewrite_attempts,
            human_review_required=human_review_required,
        ),
        reasons=review.reasons,
        artifact_refs={
            "citation_check_result": "citation_check_result.json",
            "editor_review": "editor_review.json",
            "support_matrix": "support_matrix.json",
            "report_quality_summary": "report_quality_summary.json",
            "quality_gate_metrics": "quality_gate_metrics.json",
            "quality_events": "quality_events.json",
        },
        citation_check_result=citation_check,
        editor_review=review,
        support_matrix=support_matrix,
        report_quality_summary=quality_summary,
        quality_gate_metrics=quality_gate_metrics,
        metadata={
            "source": "daily.quality_gate",
            "failure_route": route if review.decision != EditorDecision.PASS else None,
            "citation_failure_categories": [
                category.to_dict() for category in citation_check.failure_categories
            ],
            "accepted_claims_count": quality_summary.accepted_claims_count,
            "rejected_claims_count": quality_summary.rejected_claims_count,
            "uncertain_claims_count": quality_summary.uncertain_claims_count,
            "unsupported_claims_count": quality_summary.unsupported_claims_count,
            "high_severity_unsupported_claims_count": (
                quality_summary.high_severity_unsupported_claims_count
            ),
            "remediation": list(review.required_changes),
        },
    )


def _quality_route_history(
    *,
    route: str,
    review: Any,
    rewrite_attempts: int,
    human_review_required: bool,
) -> list[str]:
    history = []
    if rewrite_attempts > 0:
        history.append("rewrite")
    if review.decision == EditorDecision.BLOCKED:
        history.append("blocked")
    if human_review_required:
        history.append("human_review")
    if not history:
        history.append(route)
    return history
