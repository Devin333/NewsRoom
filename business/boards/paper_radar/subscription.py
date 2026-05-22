from __future__ import annotations

from typing import Any

from business.foundation.subscription import SubscriptionPayload, SubscriptionPayloadBuilder


PAPER_RADAR_SUBSCRIPTION_TAGS = ["paper", "arxiv", "research", "benchmark"]
PAPER_RADAR_SOURCE_TYPES = ["arxiv", "paper"]


def build_paper_radar_subscription_payload(
    *,
    run_id: str,
    cards: list[Any],
    summary: str,
    topic: str | None = None,
    quality_score: float | None = None,
) -> SubscriptionPayload:
    return SubscriptionPayloadBuilder().build(
        run_id=run_id,
        board_type="paper_radar",
        topic=topic,
        cards=cards,
        summary=summary,
        quality_score=quality_score,
        tags=PAPER_RADAR_SUBSCRIPTION_TAGS,
        source_types=PAPER_RADAR_SOURCE_TYPES,
    )


__all__ = ["PAPER_RADAR_SOURCE_TYPES", "PAPER_RADAR_SUBSCRIPTION_TAGS", "build_paper_radar_subscription_payload"]
