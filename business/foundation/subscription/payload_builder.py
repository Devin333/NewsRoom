from __future__ import annotations

from typing import Any

from business.foundation.subscription.matcher import board_subscription_defaults, extract_entities_from_cards
from business.foundation.subscription.models import SubscriptionPayload, SubscriptionTarget


class SubscriptionPayloadBuilder:
    def build(
        self,
        *,
        run_id: str,
        board_type: str,
        cards: list[Any],
        summary: str,
        topic: str | None = None,
        quality_score: float | None = None,
        tags: list[str] | None = None,
        source_types: list[str] | None = None,
        delivery_hints: dict[str, Any] | None = None,
    ) -> SubscriptionPayload:
        default_tags, default_source_types = board_subscription_defaults(board_type)
        entities = extract_entities_from_cards(cards)
        target = SubscriptionTarget(
            board_type=board_type,
            topic=topic,
            tags=_stable_unique([*(tags or []), *default_tags]),
            entities=entities or [topic] if topic else entities,
            source_types=_stable_unique([*(source_types or []), *default_source_types]),
            priority=_priority(quality_score, len(cards)),
        )
        return SubscriptionPayload(
            run_id=run_id,
            board_type=board_type,
            topic=topic,
            targets=[target],
            cards=[_payload(card) for card in cards],
            summary=summary,
            quality_score=quality_score,
            delivery_hints={
                "subscription_ready": bool(cards),
                "card_count": len(cards),
                "delivery_plan_hint": "standard_digest",
                **dict(delivery_hints or {}),
            },
        )


def aggregate_payloads(
    run_id: str,
    payloads: list[SubscriptionPayload],
    *,
    topic: str | None = None,
) -> SubscriptionPayload:
    cards: list[dict[str, Any]] = []
    targets: list[SubscriptionTarget] = []
    quality_values: list[float] = []
    for payload in payloads:
        cards.extend(payload.cards)
        targets.extend(payload.targets)
        if payload.quality_score is not None:
            quality_values.append(payload.quality_score)
    quality_score = round(sum(quality_values) / len(quality_values), 4) if quality_values else None
    return SubscriptionPayload(
        run_id=run_id,
        board_type="cross_board",
        topic=topic,
        targets=targets,
        cards=cards,
        summary=f"Cross-board subscription payload for {len(payloads)} board(s).",
        quality_score=quality_score,
        delivery_hints={
            "subscription_ready": bool(cards),
            "payload_count": len(payloads),
            "delivery_plan_hint": "topic_digest" if topic else "cross_board_digest",
        },
    )


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _stable_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _priority(quality_score: float | None, card_count: int) -> str:
    if card_count == 0:
        return "low"
    if quality_score is not None and quality_score >= 0.85:
        return "high"
    return "normal"


__all__ = ["SubscriptionPayloadBuilder", "aggregate_payloads"]
