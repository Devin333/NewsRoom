from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.quality_context_projection import (
    DailyQualityContextProjectionInput,
    DailyQualityContextProjectionService,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_models import (
    DailyQualityGateInput,
    QualityGateContext,
)


class DailyQualityGateContextService:
    def __init__(
        self,
        *,
        projection_service: DailyQualityContextProjectionService | None = None,
    ) -> None:
        self.projection_service = projection_service or DailyQualityContextProjectionService()

    def load(self, payload: DailyQualityGateInput) -> QualityGateContext:
        quality_events = list(payload.quality_events)
        projection = self.projection_service.build(
            DailyQualityContextProjectionInput(
                report_draft=payload.report_draft,
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
            report_draft=payload.report_draft,
            evidence_bundle=payload.evidence_bundle,
            verified_findings=payload.verified_findings,
            quality_events=quality_events,
            memory_context=projection.memory_context,
            historian_context=projection.historian_context,
            memory_quality_result=memory_quality_result,
        )


__all__ = ["DailyQualityGateContextService"]
