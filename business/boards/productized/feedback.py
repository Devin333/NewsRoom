from __future__ import annotations

from typing import Any

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService


class ProductizedFeedbackLearningService:
    def __init__(
        self,
        *,
        feedback_service: BoardFeedbackService,
        improvement_service: BoardImprovementService,
    ) -> None:
        self.feedback_service = feedback_service
        self.improvement_service = improvement_service

    def collect(self, *, board_run_result: Any) -> dict[str, Any]:
        events = self.feedback_service.collect(
            board_run_result=board_run_result,
            quality_summary=board_run_result.quality_summary,
        )
        events = self.improvement_service.collect_feedback(events)
        signals = self.improvement_service.build_learning_signals(events)
        return {
            "feedback_events": [event.to_dict() for event in events],
            "learning_signals": [signal.to_dict() for signal in signals],
        }


__all__ = ["ProductizedFeedbackLearningService"]
