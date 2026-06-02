from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from business.layers.analysis.quality import EditorDecision, EditorReview, RewritePolicy
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.quality_context_projection import (
    DailyQualityContextProjectionInput,
    DailyQualityContextProjectionService,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import evaluate_report_quality
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_outputs import (
    DailyQualityGateOutputInput,
    build_quality_gate_outputs,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    assess_non_social_media_bypass,
    build_non_social_media_pass_review,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    human_review_request as build_human_review_request,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_rewrite import rewrite_report_draft
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class DailyQualityGateInput:
    report_draft: dict[str, Any]
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    memory_context: dict[str, Any] | None = None
    historian_context: dict[str, Any] | None = None
    memory_repository: IntelligenceMemoryQueryRepository | None = None


@dataclass(frozen=True)
class QualityGateContext:
    report_draft: dict[str, Any]
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    memory_context: dict[str, Any] | None
    historian_context: dict[str, Any] | None
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


def evaluate_daily_quality_gate(payload: DailyQualityGateInput) -> dict[str, Any]:
    context = _load_quality_context(payload)
    evaluation = _evaluate_quality_gate(context)
    return _build_quality_outputs(context, evaluation)


def _load_quality_context(payload: DailyQualityGateInput) -> QualityGateContext:
    report_draft = payload.report_draft
    evidence_bundle = payload.evidence_bundle
    verified_findings = payload.verified_findings
    quality_events = list(payload.quality_events)
    projection = DailyQualityContextProjectionService().build(
        DailyQualityContextProjectionInput(
            report_draft=report_draft,
            memory_context=payload.memory_context,
            historian_context=payload.historian_context,
            memory_repository=payload.memory_repository,
        )
    )
    memory_quality_result = projection.memory_quality_result
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
        memory_context=projection.memory_context,
        historian_context=projection.historian_context,
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
    bypass_assessment = assess_non_social_media_bypass(context.evidence_bundle)

    if bypass_assessment.should_bypass:
        context.quality_events.append(
            quality_event(
                "quality_gate_bypassed_non_social_media",
                **bypass_assessment.event_metadata,
            )
        )
        review = build_non_social_media_pass_review(
            citation_check=citation_check,
            quality_summary=quality_summary,
        )

    final_report_draft = context.report_draft
    rewritten_report_draft = None
    rewrite_attempts = 0

    if bypass_assessment.strict_gate_required and review.decision == EditorDecision.REWRITE_REQUIRED:
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
        if bypass_assessment.strict_gate_required
        else None
    )
    if bypass_assessment.strict_gate_required and _has_critical_memory_issue(context.memory_quality_result):
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
    return build_quality_gate_outputs(
        DailyQualityGateOutputInput(
            report_draft=context.report_draft,
            final_report_draft=evaluation.final_report_draft,
            evidence_bundle=context.evidence_bundle,
            verified_findings=context.verified_findings,
            quality_events=context.quality_events,
            memory_context=context.memory_context,
            historian_context=context.historian_context,
            memory_quality_result=context.memory_quality_result,
            citation_check=evaluation.citation_check,
            support_matrix=evaluation.support_matrix,
            quality_summary=evaluation.quality_summary,
            review=evaluation.review,
            rewrite_policy=evaluation.rewrite_policy,
            rewritten_report_draft=evaluation.rewritten_report_draft,
            rewrite_attempts=evaluation.rewrite_attempts,
            human_review_request=evaluation.human_review_request,
            human_review_required=evaluation.human_review_required,
        )
    )


def _has_critical_memory_issue(memory_quality_result: dict[str, Any]) -> bool:
    return any(
        isinstance(issue, dict) and issue.get("severity") == "critical"
        for issue in memory_quality_result.get("issues") or []
    )
