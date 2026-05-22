from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from infrastructure.storage.subscriptions import (
    LocalJsonTopicSubscriptionStore,
    SubscriptionCadence,
    TopicSubscription,
)
from business.foundation.subscription import DeliveryPlan, DeliveryPlanBuilder, SubscriptionPayload, SubscriptionTarget


DEFAULT_SUBSCRIPTION_STORE_PATH = ".newsroom/subscriptions/subscriptions.json"


class TopicSubscriptionStore(Protocol):
    def list_subscriptions(
        self,
        *,
        enabled_only: bool = False,
        cadence: SubscriptionCadence | str | None = None,
    ) -> list[TopicSubscription]: ...

    def get_subscription(self, subscription_id: str) -> TopicSubscription: ...

    def upsert_subscription(self, subscription: TopicSubscription) -> TopicSubscription: ...

    def set_enabled(self, subscription_id: str, *, enabled: bool) -> TopicSubscription: ...

    def delete_subscription(self, subscription_id: str) -> bool: ...


@dataclass(frozen=True)
class TopicSubscriptionListResult:
    subscriptions: list[TopicSubscription]

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscription_count": len(self.subscriptions),
            "subscriptions": [subscription.to_dict() for subscription in self.subscriptions],
        }


class SubscriptionApplicationService:
    def __init__(
        self,
        store: TopicSubscriptionStore | None = None,
        *,
        store_path: str | Path = DEFAULT_SUBSCRIPTION_STORE_PATH,
    ) -> None:
        self.store = store or LocalJsonTopicSubscriptionStore(store_path)

    def create_topic_subscription(
        self,
        *,
        topic: str,
        cadence: SubscriptionCadence | str = SubscriptionCadence.WEEKLY,
        profile: str = "live-offline",
        source_limit: int = 5,
        subscription_id: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TopicSubscription:
        actual_cadence = SubscriptionCadence(cadence)
        subscription = TopicSubscription(
            subscription_id=subscription_id or _subscription_id(topic=topic, cadence=actual_cadence),
            topic=topic,
            cadence=actual_cadence,
            profile=profile,
            source_limit=source_limit,
            enabled=enabled,
            metadata=metadata or {},
        )
        return self.store.upsert_subscription(subscription)

    def list_topic_subscriptions(
        self,
        *,
        enabled_only: bool = False,
        cadence: SubscriptionCadence | str | None = None,
    ) -> TopicSubscriptionListResult:
        return TopicSubscriptionListResult(
            subscriptions=self.store.list_subscriptions(enabled_only=enabled_only, cadence=cadence)
        )

    def set_enabled(self, subscription_id: str, *, enabled: bool) -> TopicSubscription:
        return self.store.set_enabled(subscription_id, enabled=enabled)

    def delete_topic_subscription(self, subscription_id: str) -> bool:
        return self.store.delete_subscription(subscription_id)

    def build_delivery_plan_from_board_payload(self, payload: SubscriptionPayload | dict[str, Any]) -> DeliveryPlan:
        subscription_payload = _subscription_payload(payload)
        if subscription_payload.board_type == "cross_board":
            raise ValueError("expected board subscription payload, got cross_board")
        return DeliveryPlanBuilder().build(subscription_payload)

    def build_delivery_plan_from_cross_board_payload(self, payload: SubscriptionPayload | dict[str, Any]) -> DeliveryPlan:
        subscription_payload = _subscription_payload(payload)
        if subscription_payload.board_type != "cross_board":
            raise ValueError("expected cross_board subscription payload")
        return DeliveryPlanBuilder().build(subscription_payload, channels=["email_digest", "topic_digest"])


def _subscription_id(*, topic: str, cadence: SubscriptionCadence) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    if not normalized:
        normalized = "topic"
    normalized = normalized[:48].strip("-") or "topic"
    digest = hashlib.sha256(f"{cadence.value}:{topic}".encode("utf-8")).hexdigest()[:8]
    return f"{cadence.value}:{normalized}:{digest}"


def _subscription_payload(value: SubscriptionPayload | dict[str, Any]) -> SubscriptionPayload:
    if isinstance(value, SubscriptionPayload):
        _validate_payload(value)
        return value
    if not isinstance(value, dict):
        raise ValueError("subscription payload must be a dict or SubscriptionPayload")
    targets = []
    for item in value.get("targets") or []:
        if isinstance(item, SubscriptionTarget):
            targets.append(item)
        elif isinstance(item, dict):
            targets.append(
                SubscriptionTarget(
                    board_type=str(item.get("board_type") or value.get("board_type") or ""),
                    topic=item.get("topic", value.get("topic")),
                    tags=[str(tag) for tag in item.get("tags") or []],
                    entities=[str(entity) for entity in item.get("entities") or []],
                    source_types=[str(source_type) for source_type in item.get("source_types") or []],
                    priority=str(item.get("priority") or "normal"),
                )
            )
    payload = SubscriptionPayload(
        run_id=str(value.get("run_id") or ""),
        board_type=str(value.get("board_type") or ""),
        topic=value.get("topic"),
        targets=targets,
        cards=[dict(card) for card in value.get("cards") or [] if isinstance(card, dict)],
        summary=str(value.get("summary") or ""),
        quality_score=_optional_float(value.get("quality_score")),
        delivery_hints=dict(value.get("delivery_hints") or {}),
    )
    _validate_payload(payload)
    return payload


def _validate_payload(payload: SubscriptionPayload) -> None:
    if not payload.run_id:
        raise ValueError("subscription payload run_id is required")
    if not payload.board_type:
        raise ValueError("subscription payload board_type is required")
    if not payload.targets:
        raise ValueError("subscription payload targets are required")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid quality_score: {value}") from exc
