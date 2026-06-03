from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.quality_gate_context import (
    DailyQualityGateContextService,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_evaluation import (
    DailyQualityGateEvaluationService,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_models import (
    DailyQualityGateInput,
    QualityGateContext,
    QualityGateEvaluation,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_outputs import (
    DailyQualityGateOutputInput,
    build_quality_gate_outputs,
)


def evaluate_daily_quality_gate(payload: DailyQualityGateInput) -> dict[str, Any]:
    context = DailyQualityGateContextService().load(payload)
    evaluation = DailyQualityGateEvaluationService().evaluate(context)
    return _build_quality_outputs(context, evaluation)


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


__all__ = [
    "DailyQualityGateInput",
    "QualityGateContext",
    "QualityGateEvaluation",
    "evaluate_daily_quality_gate",
]
