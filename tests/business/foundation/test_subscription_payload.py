from __future__ import annotations

from business.foundation.subscription import DeliveryPlanBuilder, SubscriptionPayloadBuilder, aggregate_payloads


def test_subscription_payload_builder_maps_cards_targets_and_delivery_plan() -> None:
    payload = SubscriptionPayloadBuilder().build(
        run_id="run-1",
        board_type="ai_news",
        topic="Agent Memory",
        cards=[
            {
                "card_id": "card-1",
                "title": "OpenAI Agent Memory",
                "summary": "summary",
                "entities": [{"name": "OpenAI"}],
            }
        ],
        summary="summary",
        quality_score=0.9,
    )
    plan = DeliveryPlanBuilder().build(payload)

    assert payload.targets[0].tags[:3] == ["ai_news", "product_update", "industry"]
    assert "OpenAI" in payload.targets[0].entities
    assert payload.targets[0].source_types
    assert payload.cards[0]["card_id"] == "card-1"
    assert plan.priority == "high"


def test_cross_board_subscription_payload_aggregates_board_payloads() -> None:
    builder = SubscriptionPayloadBuilder()
    payloads = [
        builder.build(run_id="run-ai", board_type="ai_news", topic="Agent Memory", cards=[{"card_id": "a"}], summary="a"),
        builder.build(run_id="run-project", board_type="project_radar", topic="Agent Memory", cards=[{"card_id": "p"}], summary="p"),
    ]

    aggregate = aggregate_payloads("cross-run", payloads, topic="Agent Memory")

    assert aggregate.board_type == "cross_board"
    assert len(aggregate.targets) == 2
    assert len(aggregate.cards) == 2
    assert aggregate.delivery_hints["subscription_ready"]
