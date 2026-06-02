from __future__ import annotations

from business.boards.productized import ProductizedSubscriptionService
from business.foundation import BoardType


class StubBoardRunResult:
    cards = [
        {
            "card_id": "card-1",
            "title": "OpenAI Agent Memory",
            "summary": "Agent Memory release summary.",
            "entities": [{"name": "OpenAI"}],
        }
    ]


def test_productized_subscription_service_builds_payload_and_delivery_plan() -> None:
    service = ProductizedSubscriptionService(board_type=BoardType.AI_NEWS)

    result = service.build(
        request={"run_id": "subscription-run", "topic": "Agent Memory"},
        board_run_result=StubBoardRunResult(),
        board_output={"metadata": {"report": {"summary": "Subscriber-facing summary."}}},
        quality_summary={"score": 0.91},
    )

    payload = result["subscription_payload"]
    assert payload["run_id"] == "subscription-run"
    assert payload["summary"] == "Subscriber-facing summary."
    assert payload["quality_score"] == 0.91
    assert payload["targets"][0]["entities"] == ["OpenAI"]
    assert payload["delivery_plan"]["priority"] == "high"


def test_productized_subscription_service_uses_board_summary_fallback() -> None:
    service = ProductizedSubscriptionService(board_type=BoardType.PROJECT_RADAR)

    result = service.build(
        request={"run_id": "subscription-fallback"},
        board_run_result=StubBoardRunResult(),
        board_output={"metadata": {}},
        quality_summary={},
    )

    assert result["subscription_payload"]["summary"] == "project_radar summary"
