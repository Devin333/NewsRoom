from __future__ import annotations

from typing import Any

from business.boards._improvement import BoardImprovementService
from business.boards.productized.context import run_id_from_request
from business.boards.productized.measurement import (
    ProductizedImprovementMeasurementInput,
    ProductizedImprovementMeasurementService,
    deduplication_result_for_measurement,
    duplicate_rate,
    evidence_coverage,
    measurement_snapshot,
)
from business.foundation import BoardType
from business.foundation.models.quality_loop import BusinessFeedbackEvent, BusinessLearningSignal


class ProductizedImprovementWorkflowService:
    def __init__(
        self,
        *,
        improvement_service: BoardImprovementService,
        board_type: BoardType | None = None,
        measurement_service: ProductizedImprovementMeasurementService | None = None,
    ) -> None:
        self.improvement_service = improvement_service
        self.board_type = board_type
        self.measurement_service = measurement_service or ProductizedImprovementMeasurementService()

    def build_outputs(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        feedback_events: list[dict[str, Any]],
        learning_signals: list[dict[str, Any]],
        subscription_payload: dict[str, Any],
        productized_run: Any | None = None,
    ) -> dict[str, Any]:
        if self.board_type is None:
            raise ValueError("board_type is required for productized improvement workflow outputs")
        return self.build(
            run_id=run_id_from_request(request, self.board_type),
            board_type=self.board_type.value,
            request=request,
            board_run_result=board_run_result,
            quality_summary=quality_summary,
            cards=cards,
            feedback_events=feedback_events,
            learning_signals=learning_signals,
            subscription_payload=subscription_payload,
            productized_run=productized_run,
        )

    def build(
        self,
        *,
        run_id: str,
        board_type: str,
        request: dict[str, Any],
        board_run_result: Any,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        feedback_events: list[dict[str, Any]],
        learning_signals: list[dict[str, Any]],
        subscription_payload: dict[str, Any],
        productized_run: Any | None = None,
    ) -> dict[str, Any]:
        parsed_feedback = [
            BusinessFeedbackEvent.model_validate(item)
            for item in feedback_events
            if isinstance(item, dict)
        ]
        parsed_learning = [
            BusinessLearningSignal.model_validate(item)
            for item in learning_signals
            if isinstance(item, dict)
        ]
        recommendations = self.improvement_service.build_recommendations(
            parsed_learning,
            board_type=board_type,
            quality_summary=quality_summary,
        )
        proposals = self.improvement_service.build_proposals(recommendations)
        improvement_context = self.improvement_service.apply_approved_policy_experiments(
            run_id=run_id,
            board_type=board_type,
        )
        measurement = (
            self.measurement_service.measure_productized(
                previous_baseline=request.get("previous_measurement_baseline"),
                quality_summary=quality_summary,
                cards=cards,
                subscription_payload=subscription_payload,
                productized_run=productized_run,
            )
            if productized_run is not None
            else self.measurement_service.measure(
                previous_baseline=request.get("previous_measurement_baseline"),
                quality_summary=quality_summary,
                cards=cards,
                board_run_result=board_run_result,
                subscription_payload=subscription_payload,
            )
        )
        report = self.improvement_service.build_report(
            feedback_events=parsed_feedback,
            learning_signals=parsed_learning,
            recommendations=recommendations,
            proposals=proposals,
            policy_experiment_application_context=improvement_context,
            measurement=measurement,
        )
        report_payload = report.to_dict()
        policy_experiment_application_context = improvement_context.to_application_dict()
        return {
            "improvement_recommendations": [item.to_dict() for item in recommendations],
            "improvement_proposals": [item.to_dict() for item in proposals],
            "policy_experiment_profiles": report_payload["policy_experiment_profiles"],
            "policy_experiment_profile_ids": report_payload["policy_experiment_profile_ids"],
            "policy_experiment_application_context": policy_experiment_application_context,
            "applied_policy_experiments": improvement_context.applied_policy_experiments,
            "skipped_policy_experiments": improvement_context.skipped_policy_experiments,
            "improvement_measurement": measurement.to_dict(),
            "self_improvement_report": report_payload,
        }

__all__ = [
    "ProductizedImprovementWorkflowService",
    "ProductizedImprovementMeasurementInput",
    "ProductizedImprovementMeasurementService",
    "deduplication_result_for_measurement",
    "duplicate_rate",
    "evidence_coverage",
    "measurement_snapshot",
]
