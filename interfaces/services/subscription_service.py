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


def _subscription_id(*, topic: str, cadence: SubscriptionCadence) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    if not normalized:
        normalized = "topic"
    normalized = normalized[:48].strip("-") or "topic"
    digest = hashlib.sha256(f"{cadence.value}:{topic}".encode("utf-8")).hexdigest()[:8]
    return f"{cadence.value}:{normalized}:{digest}"
