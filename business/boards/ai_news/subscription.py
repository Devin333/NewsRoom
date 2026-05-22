from __future__ import annotations

from typing import Any

from business.foundation.subscription import SubscriptionPayload, SubscriptionPayloadBuilder


AI_NEWS_SUBSCRIPTION_TAGS = ["ai_news", "product_update", "industry"]
AI_NEWS_SOURCE_TYPES = ["rss", "official_blog", "web"]


def build_ai_news_subscription_payload(
    *,
    run_id: str,
    cards: list[Any],
    summary: str,
    topic: str | None = None,
    quality_score: float | None = None,
) -> SubscriptionPayload:
    return SubscriptionPayloadBuilder().build(
        run_id=run_id,
        board_type="ai_news",
        topic=topic,
        cards=cards,
        summary=summary,
        quality_score=quality_score,
        tags=AI_NEWS_SUBSCRIPTION_TAGS,
        source_types=AI_NEWS_SOURCE_TYPES,
    )


__all__ = ["AI_NEWS_SOURCE_TYPES", "AI_NEWS_SUBSCRIPTION_TAGS", "build_ai_news_subscription_payload"]
