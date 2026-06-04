from __future__ import annotations

import pytest

from business.foundation.subscription import SubscriptionPayloadBuilder, aggregate_payloads
from interfaces.services.subscription_service import SubscriptionApplicationService


def test_subscription_service_builds_delivery_plan_from_board_payload(tmp_path) -> None:
    payload = SubscriptionPayloadBuilder().build(
        run_id="board-subscription-run",
        board_type="ai_news",
        topic="Agent Memory",
        cards=[_card("OpenAI Agent Memory")],
        summary="Productized board payload.",
        quality_score=0.91,
    )

    plan = SubscriptionApplicationService(store_path=tmp_path / "subscriptions.json").build_delivery_plan_from_board_payload(
        payload.to_dict()
    )

    assert plan.payload_id
    assert plan.channels == ["email_digest"]
    assert plan.priority == "high"


def test_subscription_service_builds_delivery_plan_from_cross_board_payload(tmp_path) -> None:
    board_payloads = [
        SubscriptionPayloadBuilder().build(
            run_id=f"{board_type}-run",
            board_type=board_type,
            topic="Agent Memory",
            cards=[_card(f"{board_type} Agent Memory")],
            summary="Productized board payload.",
            quality_score=0.8,
        )
        for board_type in ("ai_news", "project_radar", "research", "community_pulse")
    ]
    payload = aggregate_payloads("cross-board-run", board_payloads, topic="Agent Memory")

    plan = SubscriptionApplicationService(store_path=tmp_path / "subscriptions.json").build_delivery_plan_from_cross_board_payload(
        payload.to_dict()
    )

    assert plan.payload_id
    assert plan.channels == ["email_digest", "topic_digest"]
    assert plan.priority == "normal"


def test_subscription_service_rejects_invalid_productized_payload(tmp_path) -> None:
    service = SubscriptionApplicationService(store_path=tmp_path / "subscriptions.json")

    with pytest.raises(ValueError):
        service.build_delivery_plan_from_board_payload({"run_id": "missing-targets", "board_type": "ai_news"})


def _card(title: str) -> dict:
    return {
        "card_id": title.lower().replace(" ", "-"),
        "title": title,
        "summary": "Agent Memory subscription payload card.",
        "primary_object_ref": {"label": "Agent Memory"},
        "evidence_refs": [{"source_id": "source-1"}],
    }
