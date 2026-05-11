from datetime import UTC, datetime

import pytest

from storage.subscriptions import SubscriptionCadence, TopicSubscription


def test_topic_subscription_round_trips_payload() -> None:
    subscription = TopicSubscription(
        subscription_id="weekly:ai-policy",
        topic=" AI policy ",
        cadence="weekly",
        profile="live-offline",
        source_limit=4,
        metadata={"region": "global"},
        created_at=datetime(2026, 5, 12, tzinfo=UTC),
        updated_at=datetime(2026, 5, 12, 1, tzinfo=UTC),
    )

    restored = TopicSubscription.from_dict(subscription.to_dict())

    assert subscription.topic == "AI policy"
    assert restored == subscription
    assert restored.cadence == SubscriptionCadence.WEEKLY
    assert restored.to_dict()["created_at"] == "2026-05-12T00:00:00Z"


def test_topic_subscription_validates_required_fields_and_secret_metadata() -> None:
    with pytest.raises(ValueError, match="topic is required"):
        TopicSubscription(subscription_id="sub-1", topic="")

    with pytest.raises(ValueError, match="secret-like key"):
        TopicSubscription(subscription_id="sub-1", topic="AI", metadata={"api_key": "hidden"})

    with pytest.raises(ValueError, match="source_limit"):
        TopicSubscription(subscription_id="sub-1", topic="AI", source_limit=0)
