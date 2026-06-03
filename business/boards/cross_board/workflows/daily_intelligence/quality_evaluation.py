from __future__ import annotations

from typing import Any

from business.layers.relation.evidence import EvidenceBundle, VerifiedFindings
from business.layers.analysis.quality import (
    CitationChecker,
    EditorDecision,
    EditorGate,
    QualityEvent,
    QualityScorer,
    RewritePolicy,
    SupportMatrixBuilder,
)
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.source_gate_evidence import (
    SourceGateEvidenceBundleView,
)


def evaluate_report_quality(
    report_draft: dict[str, Any],
    evidence_bundle: EvidenceBundle,
    verified_findings: VerifiedFindings,
    *,
    quality_events: list[QualityEvent],
    rewrite_policy: RewritePolicy,
    rewrite_attempts: int,
) -> dict[str, Any]:
    quality_events.append(
        quality_event(
            "citation_check_started",
            evidence_items_count=SourceGateEvidenceBundleView.from_bundle(evidence_bundle).item_count,
            rewrite_attempt=rewrite_attempts,
        )
    )
    citation_check = CitationChecker().check(report_draft, evidence_bundle, verified_findings)
    quality_events.append(
        quality_event(
            "citation_check_succeeded" if citation_check.passed else "citation_check_failed",
            unsupported_urls_count=len(citation_check.unknown_urls) + len(citation_check.unsupported_urls),
            unknown_urls_count=len(citation_check.unknown_urls),
            unsupported_evidence_ids_count=len(citation_check.unsupported_evidence_ids),
            missing_section_sources_count=len(citation_check.missing_section_sources),
            unsupported_claims_count=len(citation_check.unsupported_claims),
            rejected_claim_usage_count=len(citation_check.rejected_claim_usage),
            citation_failure_category_count=len(citation_check.failure_categories),
            citation_failure_categories=[
                category.code for category in citation_check.failure_categories
            ],
            citation_coverage_score=citation_check.citation_coverage_score,
            claim_support_score=citation_check.claim_support_score,
            rewrite_attempt=rewrite_attempts,
        )
    )
    support_matrix = SupportMatrixBuilder().build(
        report_draft,
        evidence_bundle,
        verified_findings,
    )
    quality_summary = QualityScorer().score(
        report=report_draft,
        citation_check=citation_check,
        support_matrix=support_matrix,
    )
    quality_events.append(
        quality_event(
            "editor_gate_started",
            quality_score=quality_summary.quality_score,
            rewrite_attempt=rewrite_attempts,
        )
    )
    review = EditorGate().review(
        citation_check,
        support_matrix,
        quality_summary,
        rewrite_policy=rewrite_policy,
        rewrite_attempts=rewrite_attempts,
    )
    quality_events.append(
        quality_event(
            _editor_event_type(review.decision),
            decision=review.decision.value,
            quality_score=quality_summary.quality_score,
            reason_count=len(review.reasons),
            rewrite_attempt=rewrite_attempts,
        )
    )
    return {
        "citation_check": citation_check,
        "support_matrix": support_matrix,
        "quality_summary": quality_summary,
        "review": review,
    }


def _editor_event_type(decision: EditorDecision) -> str:
    if decision == EditorDecision.PASS:
        return "editor_gate_passed"
    if decision == EditorDecision.REWRITE_REQUIRED:
        return "editor_gate_rewrite_required"
    return "editor_gate_blocked"
