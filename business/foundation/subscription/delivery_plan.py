from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha1

from business.foundation.subscription.models import DeliveryPlan, SubscriptionPayload


class DeliveryPlanBuilder:
    def build(self, payload: SubscriptionPayload, *, channels: list[str] | None = None) -> DeliveryPlan:
        selected_channels = channels or ["email_digest"]
        priority = _priority(payload)
        return DeliveryPlan(
            payload_id=_payload_id(payload),
            channels=selected_channels,
            priority=priority,
            reason=f"{payload.board_type} payload has {len(payload.cards)} card(s).",
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )


def _payload_id(payload: SubscriptionPayload) -> str:
    digest = sha1(f"{payload.run_id}|{payload.board_type}|{payload.topic}".encode("utf-8")).hexdigest()[:12]
    return f"sub_{digest}"


def _priority(payload: SubscriptionPayload) -> str:
    if payload.quality_score is not None and payload.quality_score >= 0.85:
        return "high"
    if not payload.cards:
        return "low"
    return "normal"


__all__ = ["DeliveryPlanBuilder"]
