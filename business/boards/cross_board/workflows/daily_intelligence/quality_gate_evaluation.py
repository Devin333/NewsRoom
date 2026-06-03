from __future__ import annotations

from dataclasses import replace

from business.layers.analysis.quality import EditorDecision, RewritePolicy
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.memory_quality import (
    has_critical_memory_quality_issue,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import (
    evaluate_report_quality,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_models import (
    QualityGateContext,
    QualityGateEvaluation,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    assess_non_social_media_bypass,
    build_non_social_media_pass_review,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    human_review_request as build_human_review_request,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_rewrite import (
    rewrite_report_draft,
)


class DailyQualityGateEvaluationService:
    def evaluate(self, context: QualityGateContext) -> QualityGateEvaluation:
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
        if (
            bypass_assessment.strict_gate_required
            and has_critical_memory_quality_issue(context.memory_quality_result)
        ):
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


__all__ = ["DailyQualityGateEvaluationService"]
