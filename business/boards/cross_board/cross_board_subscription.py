from __future__ import annotations

from typing import Any

from business.foundation.subscription import DeliveryPlan, DeliveryPlanBuilder, SubscriptionPayload, SubscriptionTarget, aggregate_payloads


class CrossBoardSubscriptionBuilder:
    def build(
        self,
        board_payloads: dict[str, dict[str, Any]],
        *,
        run_id: str = "cross-board-productized",
        topic: str | None = None,
    ) -> dict[str, Any]:
        payloads = [
            _subscription_payload(payload.get("subscription_payload"))
            for payload in board_payloads.values()
            if isinstance(payload.get("subscription_payload"), dict)
        ]
        aggregate = aggregate_payloads(run_id, payloads, topic=topic)
        delivery_plan = DeliveryPlanBuilder().build(aggregate)
        return {**aggregate.to_dict(), "delivery_plan": delivery_plan.to_dict()}


def _subscription_payload(payload: Any) -> SubscriptionPayload:
    if isinstance(payload, SubscriptionPayload):
        return payload
    data = dict(payload or {})
    targets = [
        target if isinstance(target, SubscriptionTarget) else SubscriptionTarget(**dict(target))
        for target in data.get("targets") or []
        if isinstance(target, (dict, SubscriptionTarget))
    ]
    return SubscriptionPayload(
        run_id=str(data.get("run_id") or "board-run"),
        board_type=str(data.get("board_type") or "unknown"),
        topic=data.get("topic"),
        targets=targets,
        cards=[dict(card) for card in data.get("cards") or [] if isinstance(card, dict)],
        summary=str(data.get("summary") or ""),
        quality_score=_optional_float(data.get("quality_score")),
        delivery_hints=dict(data.get("delivery_hints") or {}),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["CrossBoardSubscriptionBuilder"]
