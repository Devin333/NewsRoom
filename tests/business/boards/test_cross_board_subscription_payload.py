from __future__ import annotations

from interfaces.services.board_service import BoardApplicationService
from business.evaluation.fixtures import sample_signal


def test_cross_board_productized_output_aggregates_subscription_payloads() -> None:
    result = BoardApplicationService().build_productized_cross_board_output(
        [
            sample_signal("ai_news"),
            sample_signal("github_project"),
            sample_signal("paper"),
            sample_signal("community_discussion"),
        ],
        topic="Agent Memory",
    )

    payload = result["subscription_payload"]
    assert payload["board_type"] == "cross_board"
    assert len(payload["targets"]) == 4
    assert payload["delivery_plan"]["channels"]
