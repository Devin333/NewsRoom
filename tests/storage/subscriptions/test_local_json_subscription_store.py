import pytest

from storage.subscriptions import (
    LocalJsonTopicSubscriptionStore,
    TopicSubscription,
    TopicSubscriptionNotFoundError,
)


def test_local_json_subscription_store_persists_records(tmp_path) -> None:
    path = tmp_path / "subscriptions.json"
    store = LocalJsonTopicSubscriptionStore(path)

    store.upsert_subscription(
        TopicSubscription(
            subscription_id="weekly:ai",
            topic="AI",
            cadence="weekly",
            metadata={"region": "global"},
        )
    )

    restored = LocalJsonTopicSubscriptionStore(path).get_subscription("weekly:ai")

    assert restored.topic == "AI"
    assert restored.metadata == {"region": "global"}


def test_local_json_subscription_store_filters_and_toggles_enabled(tmp_path) -> None:
    store = LocalJsonTopicSubscriptionStore(tmp_path / "subscriptions.json")
    store.upsert_subscription(TopicSubscription(subscription_id="weekly:ai", topic="AI", cadence="weekly"))
    store.upsert_subscription(
        TopicSubscription(subscription_id="daily:chips", topic="Chips", cadence="daily", enabled=False)
    )

    assert [item.subscription_id for item in store.list_subscriptions(enabled_only=True)] == ["weekly:ai"]
    assert [item.subscription_id for item in store.list_subscriptions(cadence="daily")] == ["daily:chips"]

    enabled = store.set_enabled("daily:chips", enabled=True)
    assert enabled.enabled is True


def test_local_json_subscription_store_deletes_records(tmp_path) -> None:
    store = LocalJsonTopicSubscriptionStore(tmp_path / "subscriptions.json")
    store.upsert_subscription(TopicSubscription(subscription_id="weekly:ai", topic="AI"))

    assert store.delete_subscription("weekly:ai") is True
    assert store.delete_subscription("weekly:ai") is False
    with pytest.raises(TopicSubscriptionNotFoundError):
        store.get_subscription("weekly:ai")
