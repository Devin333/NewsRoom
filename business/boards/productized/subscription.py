from __future__ import annotations

from typing import Any

from business.boards.productized.context import run_id_from_request
from business.foundation import BoardType
from business.foundation.subscription import DeliveryPlanBuilder, SubscriptionPayloadBuilder


class ProductizedSubscriptionService:
    def __init__(self, *, board_type: BoardType) -> None:
        self.board_type = board_type
        self.payload_builder = SubscriptionPayloadBuilder()
        self.delivery_plan_builder = DeliveryPlanBuilder()

    def build(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        board_output: dict[str, Any],
        quality_summary: dict[str, Any],
        report_summary: str | None = None,
    ) -> dict[str, Any]:
        quality_score = quality_summary.get("score") if isinstance(quality_summary, dict) else None
        payload = self.payload_builder.build(
            run_id=run_id_from_request(request, self.board_type),
            board_type=self.board_type.value,
            topic=request.get("topic"),
            cards=board_run_result.cards,
            summary=_subscription_summary(
                report_summary=report_summary,
                board_output=board_output,
                board_type=self.board_type,
            ),
            quality_score=float(quality_score) if quality_score is not None else None,
        )
        delivery_plan = self.delivery_plan_builder.build(payload)
        return {"subscription_payload": {**payload.to_dict(), "delivery_plan": delivery_plan.to_dict()}}


def _subscription_summary(
    *,
    report_summary: str | None,
    board_output: dict[str, Any],
    board_type: BoardType,
) -> str:
    if report_summary and report_summary.strip():
        return report_summary.strip()
    report = board_output.get("metadata", {}).get("report", {}) if isinstance(board_output, dict) else {}
    summary = report.get("summary") if isinstance(report, dict) else None
    return str(summary or f"{board_type.value} summary")


__all__ = ["ProductizedSubscriptionService"]
