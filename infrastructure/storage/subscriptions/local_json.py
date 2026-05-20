from __future__ import annotations

import json
from pathlib import Path

from infrastructure.storage.subscriptions.models import (
    SubscriptionCadence,
    TopicSubscription,
    TopicSubscriptionNotFoundError,
)


SUBSCRIPTION_STORE_SCHEMA_VERSION = "topic_subscription_store.v1"


class LocalJsonTopicSubscriptionStore:
    def __init__(self, path: str | Path = ".newsroom/subscriptions/subscriptions.json") -> None:
        self.path = Path(path)

    def list_subscriptions(
        self,
        *,
        enabled_only: bool = False,
        cadence: SubscriptionCadence | str | None = None,
    ) -> list[TopicSubscription]:
        records = sorted(self._read_records().values(), key=lambda item: item.subscription_id)
        if enabled_only:
            records = [record for record in records if record.enabled]
        if cadence is not None:
            actual_cadence = SubscriptionCadence(cadence)
            records = [record for record in records if record.cadence == actual_cadence]
        return records

    def get_subscription(self, subscription_id: str) -> TopicSubscription:
        records = self._read_records()
        try:
            return records[subscription_id]
        except KeyError as exc:
            raise TopicSubscriptionNotFoundError(subscription_id) from exc

    def upsert_subscription(self, subscription: TopicSubscription) -> TopicSubscription:
        records = self._read_records()
        records[subscription.subscription_id] = subscription
        self._write_records(records)
        return subscription

    def set_enabled(self, subscription_id: str, *, enabled: bool) -> TopicSubscription:
        subscription = self.get_subscription(subscription_id)
        updated = subscription.with_enabled(enabled)
        self.upsert_subscription(updated)
        return updated

    def delete_subscription(self, subscription_id: str) -> bool:
        records = self._read_records()
        if subscription_id not in records:
            return False
        records.pop(subscription_id)
        self._write_records(records)
        return True

    def _read_records(self) -> dict[str, TopicSubscription]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        subscriptions = payload.get("subscriptions", [])
        records = [TopicSubscription.from_dict(item) for item in subscriptions]
        return {record.subscription_id: record for record in records}

    def _write_records(self, records: dict[str, TopicSubscription]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SUBSCRIPTION_STORE_SCHEMA_VERSION,
            "subscriptions": [
                record.to_dict()
                for record in sorted(records.values(), key=lambda item: item.subscription_id)
            ],
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
