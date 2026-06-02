from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    quality_gate_metrics as build_quality_gate_metrics,
    quality_result as build_quality_result,
    quality_route as build_quality_route,
)
from business.foundation.models.report_output import BlockedReport, FinalReport, render_markdown
from business.layers.analysis.quality import EditorDecision


@dataclass(frozen=True)
class DailyQualityGateOutputInput:
    report_draft: dict[str, Any]
    final_report_draft: dict[str, Any]
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    memory_context: dict[str, Any] | None
    historian_context: dict[str, Any] | None
    memory_quality_result: dict[str, Any]
    citation_check: Any
    support_matrix: Any
    quality_summary: Any
    review: Any
    rewrite_policy: Any
    rewritten_report_draft: dict[str, Any] | None
    rewrite_attempts: int
    human_review_request: Any | None
    human_review_required: bool


def build_quality_gate_outputs(payload: DailyQualityGateOutputInput) -> dict[str, Any]:
    quality_gate_metrics = build_quality_gate_metrics(
        evidence_bundle=payload.evidence_bundle,
        verified_findings=payload.verified_findings,
        citation_check=payload.citation_check,
        support_matrix=payload.support_matrix,
        quality_summary=payload.quality_summary,
        review=payload.review,
        rewrite_attempts=payload.rewrite_attempts,
        human_review_required=payload.human_review_required,
        memory_quality_result=payload.memory_quality_result,
    )
    quality_route = build_quality_route(
        review=payload.review,
        rewrite_attempts=payload.rewrite_attempts,
        human_review_required=payload.human_review_required,
    )
    quality_result = build_quality_result(
        citation_check=payload.citation_check,
        support_matrix=payload.support_matrix,
        quality_summary=payload.quality_summary,
        review=payload.review,
        quality_gate_metrics=quality_gate_metrics,
        route=quality_route,
        rewrite_attempts=payload.rewrite_attempts,
        human_review_required=payload.human_review_required,
    )
    quality_result = _with_memory_quality_metadata(
        quality_result,
        memory_context=payload.memory_context,
        memory_quality_result=payload.memory_quality_result,
    )
    outputs: dict[str, Any] = {
        "citation_check_result": payload.citation_check,
        "editor_review": payload.review,
        "support_matrix": payload.support_matrix,
        "report_quality_summary": payload.quality_summary,
        "quality_events": payload.quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": quality_route,
        "rewrite_policy": payload.rewrite_policy,
        "rewrite_instructions": payload.review.rewrite_instructions,
        "memory_quality_result": payload.memory_quality_result,
    }
    if payload.rewritten_report_draft is not None:
        outputs["rewritten_report_draft"] = payload.rewritten_report_draft
    if payload.human_review_request is not None:
        outputs["human_review_request"] = payload.human_review_request
    if payload.review.decision == EditorDecision.PASS:
        final_report = _final_report(payload)
        outputs["final_report"] = final_report
        outputs["report_markdown"] = render_markdown(final_report)
    else:
        outputs["blocked_report"] = _blocked_report(payload)
    return with_namespaced_aliases(outputs)


def _final_report(payload: DailyQualityGateOutputInput) -> FinalReport:
    return FinalReport(
        title=payload.final_report_draft["title"],
        sections=payload.final_report_draft["sections"],
        source_urls=sorted(payload.evidence_bundle.source_urls),
        metadata={
            "evidence_bundle_id": payload.evidence_bundle.bundle_id,
            "quality_score": payload.quality_summary.quality_score,
            "accepted_claims_count": len(payload.verified_findings.accepted_claims),
            "rejected_claims_count": len(payload.verified_findings.rejected_claims),
            "uncertain_claims_count": len(payload.verified_findings.uncertain_claims),
            "rewrite_attempts": payload.rewrite_attempts,
            "memory_context": payload.memory_context,
            "historian": payload.historian_context,
            "memory_quality_result": payload.memory_quality_result,
        },
    )


def _blocked_report(payload: DailyQualityGateOutputInput) -> BlockedReport:
    return BlockedReport(
        title=payload.final_report_draft.get("title", "Blocked Daily Intelligence Report"),
        reasons=payload.review.reasons,
        draft=payload.final_report_draft,
        metadata={
            "citation_check_result": payload.citation_check.to_dict(),
            "citation_failure_categories": [
                category.to_dict()
                for category in payload.citation_check.failure_categories
            ],
            "editor_review": payload.review.to_dict(),
            "quality_score": payload.quality_summary.quality_score,
            "accepted_claims_count": payload.quality_summary.accepted_claims_count,
            "rejected_claims_count": payload.quality_summary.rejected_claims_count,
            "uncertain_claims_count": payload.quality_summary.uncertain_claims_count,
            "unsupported_claims_count": payload.quality_summary.unsupported_claims_count,
            "high_severity_unsupported_claims_count": (
                payload.quality_summary.high_severity_unsupported_claims_count
            ),
            "rewrite_attempts": payload.rewrite_attempts,
            "human_review_required": payload.human_review_required,
            "remediation": list(payload.review.required_changes),
            "memory_context": payload.memory_context,
            "historian": payload.historian_context,
            "memory_quality_result": payload.memory_quality_result,
        },
    )


def _with_memory_quality_metadata(
    quality_result: Any,
    *,
    memory_context: dict[str, Any] | None,
    memory_quality_result: dict[str, Any],
) -> Any:
    metadata = dict(getattr(quality_result, "metadata", {}) or {})
    metadata["memory_context"] = memory_context
    metadata["memory_quality_result"] = memory_quality_result
    return replace(quality_result, metadata=metadata)
