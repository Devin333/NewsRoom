from __future__ import annotations

from typing import Any

from framework.workflow import ScopedDataBuffer
from domain.reports import BlockedReport, FinalReport, render_markdown
from quality import EditorDecision, RewritePolicy
from workflows.daily_intelligence.evidence_step import quality_event
from workflows.daily_intelligence.quality_evaluation import evaluate_report_quality
from workflows.daily_intelligence.quality_result_builder import (
    human_review_request as build_human_review_request,
    quality_gate_metrics as build_quality_gate_metrics,
    quality_result as build_quality_result,
    quality_route as build_quality_route,
)
from workflows.daily_intelligence.quality_rewrite import rewrite_report_draft


def quality_gate(buffer: ScopedDataBuffer) -> dict[str, Any]:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    verified_findings = buffer.read("verified_findings")
    quality_events = list(buffer.read("quality_events"))
    rewrite_policy = RewritePolicy()
    evaluation = evaluate_report_quality(
        report_draft,
        evidence_bundle,
        verified_findings,
        quality_events=quality_events,
        rewrite_policy=rewrite_policy,
        rewrite_attempts=0,
    )
    citation_check = evaluation["citation_check"]
    support_matrix = evaluation["support_matrix"]
    quality_summary = evaluation["quality_summary"]
    review = evaluation["review"]
    final_report_draft = report_draft
    rewritten_report_draft = None
    rewrite_attempts = 0

    if review.decision == EditorDecision.REWRITE_REQUIRED:
        quality_events.append(
            quality_event(
                "rewrite_started",
                rewrite_attempt=1,
                instruction_count=len(review.rewrite_instructions),
            )
        )
        rewritten_report_draft = rewrite_report_draft(
            report_draft,
            evidence_bundle,
            review,
        )
        rewrite_attempts = 1
        evaluation = evaluate_report_quality(
            rewritten_report_draft,
            evidence_bundle,
            verified_findings,
            quality_events=quality_events,
            rewrite_policy=rewrite_policy,
            rewrite_attempts=rewrite_attempts,
        )
        citation_check = evaluation["citation_check"]
        support_matrix = evaluation["support_matrix"]
        quality_summary = evaluation["quality_summary"]
        review = evaluation["review"]
        if review.decision == EditorDecision.PASS:
            quality_events.append(
                quality_event(
                    "rewrite_succeeded",
                    rewrite_attempt=rewrite_attempts,
                    quality_score=quality_summary.quality_score,
                )
            )
            final_report_draft = rewritten_report_draft
        else:
            quality_events.append(
                quality_event(
                    "rewrite_failed",
                    rewrite_attempt=rewrite_attempts,
                    decision=review.decision.value,
                    reason_count=len(review.reasons),
                )
            )

    human_review_request = build_human_review_request(
        evidence_bundle=evidence_bundle,
        review=review,
        quality_summary=quality_summary,
    )
    human_review_required = human_review_request is not None
    if human_review_request:
        quality_events.append(
            quality_event(
                "human_review_requested",
                risk_level=human_review_request.risk_level,
                reason=human_review_request.reason,
            )
        )

    quality_gate_metrics = build_quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_route = build_quality_route(
        review=review,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_result = build_quality_result(
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        quality_gate_metrics=quality_gate_metrics,
        route=quality_route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    outputs: dict[str, Any] = {
        "citation_check_result": citation_check,
        "editor_review": review,
        "support_matrix": support_matrix,
        "report_quality_summary": quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": quality_route,
        "rewrite_policy": rewrite_policy,
        "rewrite_instructions": review.rewrite_instructions,
    }
    if rewritten_report_draft is not None:
        outputs["rewritten_report_draft"] = rewritten_report_draft
    if human_review_request is not None:
        outputs["human_review_request"] = human_review_request
    if review.decision == EditorDecision.PASS:
        final_report = FinalReport(
            title=final_report_draft["title"],
            sections=final_report_draft["sections"],
            source_urls=sorted(evidence_bundle.source_urls),
            metadata={
                "evidence_bundle_id": evidence_bundle.bundle_id,
                "quality_score": quality_summary.quality_score,
                "accepted_claims_count": len(verified_findings.accepted_claims),
                "rejected_claims_count": len(verified_findings.rejected_claims),
                "uncertain_claims_count": len(verified_findings.uncertain_claims),
                "rewrite_attempts": rewrite_attempts,
            },
        )
        outputs["final_report"] = final_report
        outputs["report_markdown"] = render_markdown(final_report)
    else:
        outputs["blocked_report"] = BlockedReport(
            title=final_report_draft.get("title", "Blocked Daily Intelligence Report"),
            reasons=review.reasons,
            draft=final_report_draft,
            metadata={
                "citation_check_result": citation_check.to_dict(),
                "citation_failure_categories": [
                    category.to_dict() for category in citation_check.failure_categories
                ],
                "editor_review": review.to_dict(),
                "quality_score": quality_summary.quality_score,
                "accepted_claims_count": quality_summary.accepted_claims_count,
                "rejected_claims_count": quality_summary.rejected_claims_count,
                "uncertain_claims_count": quality_summary.uncertain_claims_count,
                "unsupported_claims_count": quality_summary.unsupported_claims_count,
                "high_severity_unsupported_claims_count": (
                    quality_summary.high_severity_unsupported_claims_count
                ),
                "rewrite_attempts": rewrite_attempts,
                "human_review_required": human_review_required,
                "remediation": list(review.required_changes),
            },
        )
    return outputs
