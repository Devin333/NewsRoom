from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.foundation.models.report_output import BlockedReport, FinalReport, render_markdown
from business.layers.analysis.quality import EditorDecision, RewritePolicy
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import evaluate_report_quality
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    human_review_request as build_human_review_request,
    quality_gate_metrics as build_quality_gate_metrics,
    quality_result as build_quality_result,
    quality_route as build_quality_route,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_rewrite import rewrite_report_draft


def quality_gate(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    verified_findings = buffer.read("verified_findings")
    quality_events = list(buffer.read("quality_events"))
    memory_context = _read_memory_context(buffer)
    memory_quality_result = _memory_quality_result(memory_context)
    if memory_quality_result["memory_available"]:
        quality_events.append(
            quality_event(
                "memory_quality_checked",
                passed=memory_quality_result["passed"],
                issue_count=len(memory_quality_result["issues"]),
            )
        )
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
    quality_result = _with_memory_quality_metadata(
        quality_result,
        memory_context=memory_context,
        memory_quality_result=memory_quality_result,
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
        "memory_quality_result": memory_quality_result,
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
                "memory_context": memory_context,
                "memory_quality_result": memory_quality_result,
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
                "memory_context": memory_context,
                "memory_quality_result": memory_quality_result,
            },
        )
    return outputs


def _read_memory_context(buffer: StepScopedDataBufferView) -> dict[str, Any] | None:
    try:
        if not buffer.exists("memory_context"):
            return None
        value = buffer.read("memory_context", required=False)
    except DataBufferReadPermissionError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _memory_quality_result(memory_context: dict[str, Any] | None) -> dict[str, Any]:
    if not memory_context:
        return {
            "passed": True,
            "issues": [],
            "memory_available": False,
            "metadata": {"reason": "memory_context_missing"},
        }
    conflicts = [
        dict(conflict)
        for conflict in memory_context.get("conflicts") or []
        if isinstance(conflict, dict)
    ]
    issues = [
        {
            "issue_type": str(conflict.get("issue_type") or "memory_conflict"),
            "severity": "high",
            "target_type": "memory_context",
            "target_id": str(memory_context.get("query") or memory_context.get("topic") or ""),
            "message": str(conflict.get("message") or "Memory conflict detected"),
            "metadata": conflict,
        }
        for conflict in conflicts
    ]
    return {
        "passed": not any(issue["severity"] in {"critical", "high"} for issue in issues),
        "issues": issues,
        "memory_available": bool((memory_context.get("metadata") or {}).get("memory_available", True)),
        "metadata": {
            "query": memory_context.get("query"),
            "topic": memory_context.get("topic"),
            "claim_count": len(memory_context.get("claims") or []),
            "event_count": len(memory_context.get("events") or []),
            "conflict_count": len(conflicts),
        },
    }


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
