from __future__ import annotations

from typing import Any

from business.foundation.subscription import SubscriptionPayload, SubscriptionPayloadBuilder


COMMUNITY_PULSE_SUBSCRIPTION_TAGS = ["community", "discussion", "sentiment", "developer"]
COMMUNITY_PULSE_SOURCE_TYPES = ["reddit", "hackernews", "lobsters", "stackoverflow", "devto"]


def build_community_pulse_subscription_payload(
    *,
    run_id: str,
    cards: list[Any],
    summary: str,
    topic: str | None = None,
    quality_score: float | None = None,
) -> SubscriptionPayload:
    return SubscriptionPayloadBuilder().build(
        run_id=run_id,
        board_type="community_pulse",
        topic=topic,
        cards=cards,
        summary=summary,
        quality_score=quality_score,
        tags=COMMUNITY_PULSE_SUBSCRIPTION_TAGS,
        source_types=COMMUNITY_PULSE_SOURCE_TYPES,
    )


__all__ = ["COMMUNITY_PULSE_SOURCE_TYPES", "COMMUNITY_PULSE_SUBSCRIPTION_TAGS", "build_community_pulse_subscription_payload"]
