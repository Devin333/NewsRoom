from __future__ import annotations

from typing import Any

from business.boards._improvement import BoardImprovementService
from business.foundation.models.quality_loop import BusinessFeedbackEvent, BusinessLearningSignal


class ProductizedImprovementWorkflowService:
    def __init__(self, *, improvement_service: BoardImprovementService) -> None:
        self.improvement_service = improvement_service

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
        improvement_context = self.improvement_service.apply_approved_overrides(
            run_id=run_id,
            board_type=board_type,
        )
        measurement = self.improvement_service.measure(
            request.get("previous_measurement_baseline"),
            measurement_snapshot(
                quality_summary=quality_summary,
                cards=cards,
                board_run_result=board_run_result,
                subscription_payload=subscription_payload,
            ),
        )
        report = self.improvement_service.build_report(
            feedback_events=parsed_feedback,
            learning_signals=parsed_learning,
            recommendations=recommendations,
            proposals=proposals,
            applied_overrides=improvement_context.applied_overrides,
            measurement=measurement,
        )
        return {
            "improvement_recommendations": [item.to_dict() for item in recommendations],
            "improvement_proposals": [item.to_dict() for item in proposals],
            "applied_overrides": improvement_context.applied_overrides,
            "improvement_measurement": measurement.to_dict(),
            "self_improvement_report": report.to_dict(),
        }


def measurement_snapshot(
    *,
    quality_summary: dict[str, Any],
    cards: list[dict[str, Any]],
    board_run_result: Any,
    subscription_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "quality_score": quality_summary.get("score") if isinstance(quality_summary, dict) else None,
        "card_count": len(cards),
        "evidence_coverage": evidence_coverage(cards),
        "duplicate_rate": duplicate_rate(board_run_result),
        "empty_output": len(cards) == 0,
        "subscription_match": 1.0 if subscription_payload.get("targets") else 0.0,
    }


def evidence_coverage(cards: list[dict[str, Any]]) -> float:
    if not cards:
        return 0.0
    return round(sum(1 for card in cards if card.get("evidence_refs")) / len(cards), 4)


def duplicate_rate(result: Any) -> float:
    metadata = getattr(result, "metadata", {}) or {}
    dedupe = metadata.get("deduplication_result")
    groups = dedupe.get("event_groups") if isinstance(dedupe, dict) else []
    if not groups:
        return 0.0
    duplicate_groups = [group for group in groups if isinstance(group, dict) and len(group.get("item_ids") or []) > 1]
    return round(len(duplicate_groups) / len(groups), 4)


__all__ = [
    "ProductizedImprovementWorkflowService",
    "duplicate_rate",
    "evidence_coverage",
    "measurement_snapshot",
]
