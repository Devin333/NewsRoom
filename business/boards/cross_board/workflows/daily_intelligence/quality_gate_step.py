from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.foundation.models.report_output import BlockedReport, FinalReport, render_markdown
from business.layers.analysis.quality import EditorDecision, EditorReview, RewritePolicy
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.memory_quality import (
    DailyMemoryQualityService,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import evaluate_report_quality
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    build_non_social_media_pass_review,
    strict_quality_gate_required,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    human_review_request as build_human_review_request,
    quality_gate_metrics as build_quality_gate_metrics,
    quality_result as build_quality_result,
    quality_route as build_quality_route,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_rewrite import rewrite_report_draft
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    read_buffer_list,
)
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class QualityGateContext:
    report_draft: dict[str, Any]
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    memory_context: dict[str, Any] | None
    historian_metadata: dict[str, Any] | None
    memory_quality_result: dict[str, Any]


@dataclass(frozen=True)
class QualityGateEvaluation:
    citation_check: Any
    support_matrix: Any
    quality_summary: Any
    review: EditorReview
    rewrite_policy: RewritePolicy
    final_report_draft: dict[str, Any]
    rewritten_report_draft: dict[str, Any] | None
    rewrite_attempts: int
    human_review_request: Any | None
    human_review_required: bool


def quality_gate(
    buffer: StepScopedDataBufferView,
    *,
    memory_repository: IntelligenceMemoryQueryRepository | None = None,
) -> dict[str, Any]:
    context = _load_quality_context(buffer, memory_repository=memory_repository)
    evaluation = _evaluate_quality_gate(context)
    return _build_quality_outputs(context, evaluation)


def _load_quality_context(
    buffer: StepScopedDataBufferView,
    *,
    memory_repository: IntelligenceMemoryQueryRepository | None,
) -> QualityGateContext:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    verified_findings = buffer.read("verified_findings")
    quality_events = read_buffer_list(buffer, "quality_events")
    memory_context = _read_memory_context(buffer)
    historian_context = _read_historian_context(buffer)
    historian_metadata = _historian_metadata(historian_context, report_draft, memory_context)
    memory_quality_result = _memory_quality_result(
        memory_context,
        repository=_read_memory_query_repository(buffer, memory_repository),
    )
    memory_quality_result = _with_historian_quality_metadata(
        memory_quality_result,
        historian_metadata,
    )
    if memory_quality_result["memory_available"]:
        quality_events.append(
            quality_event(
                "memory_quality_checked",
                passed=memory_quality_result["passed"],
                issue_count=len(memory_quality_result["issues"]),
            )
        )
    return QualityGateContext(
        report_draft=report_draft,
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        quality_events=quality_events,
        memory_context=memory_context,
        historian_metadata=historian_metadata,
        memory_quality_result=memory_quality_result,
    )


def _evaluate_quality_gate(context: QualityGateContext) -> QualityGateEvaluation:
    rewrite_policy = RewritePolicy()
    evaluation = evaluate_report_quality(
        context.report_draft,
        context.evidence_bundle,
        context.verified_findings,
        quality_events=context.quality_events,
        rewrite_policy=rewrite_policy,
        rewrite_attempts=0,
    )
    citation_check = evaluation["citation_check"]
    support_matrix = evaluation["support_matrix"]
    quality_summary = evaluation["quality_summary"]
    review = evaluation["review"]
    strict_gate_required = strict_quality_gate_required(context.evidence_bundle)

    if not strict_gate_required:
        context.quality_events.append(
            quality_event(
                "quality_gate_bypassed_non_social_media",
                evidence_items_count=len(context.evidence_bundle.items),
            )
        )
        review = build_non_social_media_pass_review(
            citation_check=citation_check,
            quality_summary=quality_summary,
        )

    final_report_draft = context.report_draft
    rewritten_report_draft = None
    rewrite_attempts = 0

    if strict_gate_required and review.decision == EditorDecision.REWRITE_REQUIRED:
        context.quality_events.append(
            quality_event(
                "rewrite_started",
                rewrite_attempt=1,
                instruction_count=len(review.rewrite_instructions),
            )
        )
        rewritten_report_draft = rewrite_report_draft(
            context.report_draft,
            context.evidence_bundle,
            review,
        )
        rewrite_attempts = 1
        evaluation = evaluate_report_quality(
            rewritten_report_draft,
            context.evidence_bundle,
            context.verified_findings,
            quality_events=context.quality_events,
            rewrite_policy=rewrite_policy,
            rewrite_attempts=rewrite_attempts,
        )
        citation_check = evaluation["citation_check"]
        support_matrix = evaluation["support_matrix"]
        quality_summary = evaluation["quality_summary"]
        review = evaluation["review"]
        if review.decision == EditorDecision.PASS:
            context.quality_events.append(
                quality_event(
                    "rewrite_succeeded",
                    rewrite_attempt=rewrite_attempts,
                    quality_score=quality_summary.quality_score,
                )
            )
            final_report_draft = rewritten_report_draft
        else:
            context.quality_events.append(
                quality_event(
                    "rewrite_failed",
                    rewrite_attempt=rewrite_attempts,
                    decision=review.decision.value,
                    reason_count=len(review.reasons),
                )
            )

    human_review_request = (
        build_human_review_request(
            evidence_bundle=context.evidence_bundle,
            review=review,
            quality_summary=quality_summary,
        )
        if strict_gate_required
        else None
    )
    if strict_gate_required and _has_critical_memory_issue(context.memory_quality_result):
        review = replace(
            review,
            decision=EditorDecision.BLOCKED,
            reasons=[*review.reasons, "blocked by critical memory quality issue"],
            required_changes=[
                *review.required_changes,
                "resolve critical memory quality issue before publishing",
            ],
            block_reasons=[*review.block_reasons, "critical memory quality issue"],
            final_notes="blocked by memory quality",
        )
        human_review_request = None
    human_review_required = human_review_request is not None
    if human_review_request:
        context.quality_events.append(
            quality_event(
                "human_review_requested",
                risk_level=human_review_request.risk_level,
                reason=human_review_request.reason,
            )
        )

    return QualityGateEvaluation(
        citation_check=citation_check,
        support_matrix=support_matrix,
        quality_summary=quality_summary,
        review=review,
        rewrite_policy=rewrite_policy,
        final_report_draft=final_report_draft,
        rewritten_report_draft=rewritten_report_draft,
        rewrite_attempts=rewrite_attempts,
        human_review_request=human_review_request,
        human_review_required=human_review_required,
    )


def _build_quality_outputs(
    context: QualityGateContext,
    evaluation: QualityGateEvaluation,
) -> dict[str, Any]:
    quality_gate_metrics = build_quality_gate_metrics(
        evidence_bundle=context.evidence_bundle,
        verified_findings=context.verified_findings,
        citation_check=evaluation.citation_check,
        support_matrix=evaluation.support_matrix,
        quality_summary=evaluation.quality_summary,
        review=evaluation.review,
        rewrite_attempts=evaluation.rewrite_attempts,
        human_review_required=evaluation.human_review_required,
    )
    quality_route = build_quality_route(
        review=evaluation.review,
        rewrite_attempts=evaluation.rewrite_attempts,
        human_review_required=evaluation.human_review_required,
    )
    quality_result = build_quality_result(
        citation_check=evaluation.citation_check,
        support_matrix=evaluation.support_matrix,
        quality_summary=evaluation.quality_summary,
        review=evaluation.review,
        quality_gate_metrics=quality_gate_metrics,
        route=quality_route,
        rewrite_attempts=evaluation.rewrite_attempts,
        human_review_required=evaluation.human_review_required,
    )
    quality_result = _with_memory_quality_metadata(
        quality_result,
        memory_context=context.memory_context,
        memory_quality_result=context.memory_quality_result,
    )
    outputs: dict[str, Any] = {
        "citation_check_result": evaluation.citation_check,
        "editor_review": evaluation.review,
        "support_matrix": evaluation.support_matrix,
        "report_quality_summary": evaluation.quality_summary,
        "quality_events": context.quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": quality_route,
        "rewrite_policy": evaluation.rewrite_policy,
        "rewrite_instructions": evaluation.review.rewrite_instructions,
        "memory_quality_result": context.memory_quality_result,
    }
    if evaluation.rewritten_report_draft is not None:
        outputs["rewritten_report_draft"] = evaluation.rewritten_report_draft
    if evaluation.human_review_request is not None:
        outputs["human_review_request"] = evaluation.human_review_request
    if evaluation.review.decision == EditorDecision.PASS:
        final_report = FinalReport(
            title=evaluation.final_report_draft["title"],
            sections=evaluation.final_report_draft["sections"],
            source_urls=sorted(context.evidence_bundle.source_urls),
            metadata={
                "evidence_bundle_id": context.evidence_bundle.bundle_id,
                "quality_score": evaluation.quality_summary.quality_score,
                "accepted_claims_count": len(context.verified_findings.accepted_claims),
                "rejected_claims_count": len(context.verified_findings.rejected_claims),
                "uncertain_claims_count": len(context.verified_findings.uncertain_claims),
                "rewrite_attempts": evaluation.rewrite_attempts,
                "memory_context": context.memory_context,
                "historian": context.historian_metadata,
                "memory_quality_result": context.memory_quality_result,
            },
        )
        outputs["final_report"] = final_report
        outputs["report_markdown"] = render_markdown(final_report)
    else:
        outputs["blocked_report"] = BlockedReport(
            title=evaluation.final_report_draft.get("title", "Blocked Daily Intelligence Report"),
            reasons=evaluation.review.reasons,
            draft=evaluation.final_report_draft,
            metadata={
                "citation_check_result": evaluation.citation_check.to_dict(),
                "citation_failure_categories": [
                    category.to_dict()
                    for category in evaluation.citation_check.failure_categories
                ],
                "editor_review": evaluation.review.to_dict(),
                "quality_score": evaluation.quality_summary.quality_score,
                "accepted_claims_count": evaluation.quality_summary.accepted_claims_count,
                "rejected_claims_count": evaluation.quality_summary.rejected_claims_count,
                "uncertain_claims_count": evaluation.quality_summary.uncertain_claims_count,
                "unsupported_claims_count": evaluation.quality_summary.unsupported_claims_count,
                "high_severity_unsupported_claims_count": (
                    evaluation.quality_summary.high_severity_unsupported_claims_count
                ),
                "rewrite_attempts": evaluation.rewrite_attempts,
                "human_review_required": evaluation.human_review_required,
                "remediation": list(evaluation.review.required_changes),
                "memory_context": context.memory_context,
                "historian": context.historian_metadata,
                "memory_quality_result": context.memory_quality_result,
            },
        )
    return with_namespaced_aliases(outputs)


def _read_memory_context(buffer: StepScopedDataBufferView) -> dict[str, Any] | None:
    try:
        if not buffer.exists("memory_context"):
            return None
        value = buffer.read("memory_context", required=False)
    except DataBufferReadPermissionError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _read_historian_context(buffer: StepScopedDataBufferView) -> dict[str, Any] | None:
    try:
        if not buffer.exists("historian_context"):
            return None
        value = buffer.read("historian_context", required=False)
    except DataBufferReadPermissionError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _read_memory_query_repository(
    buffer: StepScopedDataBufferView,
    injected_repository: IntelligenceMemoryQueryRepository | None,
) -> IntelligenceMemoryQueryRepository | None:
    if injected_repository is not None:
        return injected_repository
    try:
        if not buffer.exists("memory_query_repository"):
            return None
        value = buffer.read("memory_query_repository", required=False)
    except DataBufferReadPermissionError:
        return None
    return value


def _memory_quality_result(
    memory_context: dict[str, Any] | None,
    *,
    repository: IntelligenceMemoryQueryRepository | None,
) -> dict[str, Any]:
    return DailyMemoryQualityService().evaluate(memory_context, repository=repository)


def _historian_metadata(
    historian_context: dict[str, Any] | None,
    report_draft: dict[str, Any],
    memory_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if historian_context:
        return dict(historian_context)
    report_metadata = report_draft.get("metadata") if isinstance(report_draft, dict) else None
    if isinstance(report_metadata, dict) and isinstance(report_metadata.get("historian"), dict):
        return dict(report_metadata["historian"])
    memory_metadata = memory_context.get("metadata") if memory_context else None
    if isinstance(memory_metadata, dict) and isinstance(memory_metadata.get("historian"), dict):
        return dict(memory_metadata["historian"])
    return None


def _with_historian_quality_metadata(
    memory_quality_result: dict[str, Any],
    historian_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if not historian_metadata:
        return memory_quality_result
    payload = dict(memory_quality_result)
    metadata = dict(payload.get("metadata") or {})
    raw_output = historian_metadata.get("output")
    output = dict(raw_output) if isinstance(raw_output, dict) else {}
    repeated_claims = list(output.get("repeated_claims") or [])
    contradictions = list(output.get("contradictions") or [])
    metadata["historian"] = historian_metadata
    metadata["historian_repeated_claims"] = repeated_claims
    metadata["historian_contradictions"] = contradictions
    metadata["historian_repeated_claim_count"] = len(repeated_claims)
    metadata["historian_contradiction_count"] = len(contradictions)
    payload["metadata"] = metadata
    return payload


def _has_critical_memory_issue(memory_quality_result: dict[str, Any]) -> bool:
    return any(
        isinstance(issue, dict) and issue.get("severity") == "critical"
        for issue in memory_quality_result.get("issues") or []
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
