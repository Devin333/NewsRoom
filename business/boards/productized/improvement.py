from __future__ import annotations

from typing import Any

from business.boards._improvement import BoardImprovementService
from business.boards.productized.context import run_id_from_request
from business.foundation import BoardType
from business.foundation.models.quality_loop import BusinessFeedbackEvent, BusinessLearningSignal


class ProductizedImprovementWorkflowService:
    def __init__(
        self,
        *,
        improvement_service: BoardImprovementService,
        board_type: BoardType | None = None,
    ) -> None:
        self.improvement_service = improvement_service
        self.board_type = board_type

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
        measurement = self.improvement_service.measure(
            request.get("previous_measurement_baseline"),
            measurement_snapshot(
                quality_summary=quality_summary,
                cards=cards,
                board_run_result=board_run_result,
                subscription_payload=subscription_payload,
                productized_run=productized_run,
            ),
        )
        report = self.improvement_service.build_report(
            feedback_events=parsed_feedback,
            learning_signals=parsed_learning,
            recommendations=recommendations,
            proposals=proposals,
            applied_policy_experiments=improvement_context.applied_policy_experiments,
            applied_overrides=improvement_context.applied_overrides,
            measurement=measurement,
        )
        return {
            "improvement_recommendations": [item.to_dict() for item in recommendations],
            "improvement_proposals": [item.to_dict() for item in proposals],
            "applied_policy_experiments": improvement_context.applied_policy_experiments,
            "skipped_policy_experiments": improvement_context.skipped_policy_experiments,
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
    productized_run: Any | None = None,
) -> dict[str, Any]:
    return {
        "quality_score": quality_summary.get("score") if isinstance(quality_summary, dict) else None,
        "card_count": len(cards),
        "evidence_coverage": evidence_coverage(cards),
        "duplicate_rate": duplicate_rate(board_run_result, productized_run=productized_run),
        "empty_output": len(cards) == 0,
        "subscription_match": 1.0 if subscription_payload.get("targets") else 0.0,
    }


def evidence_coverage(cards: list[dict[str, Any]]) -> float:
    if not cards:
        return 0.0
    return round(sum(1 for card in cards if card.get("evidence_refs")) / len(cards), 4)


def duplicate_rate(result: Any = None, *, productized_run: Any | None = None) -> float:
    dedupe = deduplication_result_for_measurement(
        board_run_result=result,
        productized_run=productized_run,
    )
    groups = dedupe.get("event_groups") if isinstance(dedupe, dict) else []
    if not groups:
        return 0.0
    duplicate_groups = [
        group
        for group in groups
        if isinstance(group, dict) and len(group.get("item_ids") or []) > 1
    ]
    return round(len(duplicate_groups) / len(groups), 4)


def deduplication_result_for_measurement(
    *,
    board_run_result: Any = None,
    productized_run: Any | None = None,
) -> dict[str, Any]:
    formal = _deduplication_result_from_productized_run(productized_run)
    if formal is not None:
        return formal
    return _deduplication_result_from_board_result(board_run_result) or {}


def _deduplication_result_from_productized_run(productized_run: Any | None) -> dict[str, Any] | None:
    if productized_run is None:
        return None
    if isinstance(productized_run, dict):
        value = productized_run.get("deduplication_result")
    else:
        value = getattr(productized_run, "deduplication_result", None)
    return dict(value) if isinstance(value, dict) else None


def _deduplication_result_from_board_result(result: Any) -> dict[str, Any] | None:
    metadata = getattr(result, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return None
    productized_state = metadata.get("productized_run_state")
    if (
        isinstance(productized_state, dict)
        and isinstance(productized_state.get("deduplication_result"), dict)
    ):
        return dict(productized_state["deduplication_result"])
    dedupe = metadata.get("deduplication_result")
    return dict(dedupe) if isinstance(dedupe, dict) else None


__all__ = [
    "ProductizedImprovementWorkflowService",
    "deduplication_result_for_measurement",
    "duplicate_rate",
    "evidence_coverage",
    "measurement_snapshot",
]
