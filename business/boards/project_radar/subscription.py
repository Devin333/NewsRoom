from __future__ import annotations

from typing import Any

from business.foundation.subscription import SubscriptionPayload, SubscriptionPayloadBuilder


PROJECT_RADAR_SUBSCRIPTION_TAGS = ["github", "project", "framework", "release"]
PROJECT_RADAR_SOURCE_TYPES = ["github", "hackernews", "devto"]


def build_project_radar_subscription_payload(
    *,
    run_id: str,
    cards: list[Any],
    summary: str,
    topic: str | None = None,
    quality_score: float | None = None,
) -> SubscriptionPayload:
    return SubscriptionPayloadBuilder().build(
        run_id=run_id,
        board_type="project_radar",
        topic=topic,
        cards=cards,
        summary=summary,
        quality_score=quality_score,
        tags=PROJECT_RADAR_SUBSCRIPTION_TAGS,
        source_types=PROJECT_RADAR_SOURCE_TYPES,
    )


__all__ = ["PROJECT_RADAR_SOURCE_TYPES", "PROJECT_RADAR_SUBSCRIPTION_TAGS", "build_project_radar_subscription_payload"]
