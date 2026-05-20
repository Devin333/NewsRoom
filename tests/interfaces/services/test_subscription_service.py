from interfaces.services.subscription_service import SubscriptionApplicationService
from infrastructure.storage.subscriptions import LocalJsonTopicSubscriptionStore


def test_subscription_service_creates_stable_id_and_lists(tmp_path) -> None:
    service = SubscriptionApplicationService(
        store=LocalJsonTopicSubscriptionStore(tmp_path / "subscriptions.json")
    )

    created = service.create_topic_subscription(topic="AI Policy", cadence="weekly", source_limit=3)
    listed = service.list_topic_subscriptions(cadence="weekly")

    assert created.subscription_id.startswith("weekly:ai-policy:")
    assert listed.to_dict()["subscription_count"] == 1
    assert listed.to_dict()["subscriptions"][0]["source_limit"] == 3


def test_subscription_service_enable_disable_delete(tmp_path) -> None:
    service = SubscriptionApplicationService(
        store=LocalJsonTopicSubscriptionStore(tmp_path / "subscriptions.json")
    )
    service.create_topic_subscription(subscription_id="weekly:ai", topic="AI")

    disabled = service.set_enabled("weekly:ai", enabled=False)
    enabled = service.set_enabled("weekly:ai", enabled=True)
    deleted = service.delete_topic_subscription("weekly:ai")

    assert disabled.enabled is False
    assert enabled.enabled is True
    assert deleted is True
