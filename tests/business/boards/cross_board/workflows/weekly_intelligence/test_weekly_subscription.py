from __future__ import annotations

from business.boards.cross_board.workflows.weekly_intelligence.weekly_subscription import WeeklySubscriptionBuilder


def test_weekly_subscription_builder_creates_payload_and_delivery_plan() -> None:
    payload = WeeklySubscriptionBuilder().build(
        run_id="weekly-run",
        topic="Agent Memory",
        source_reports=[{"report_id": "r1", "source_urls": ["https://example.com"]}],
        weekly_trends={"high_confidence_trends": [{"trend_id": "t1", "topic": "workflow", "source_report_count": 1}], "recurring_entities": [{"entity": "OpenAI"}]},
        weekly_quality={"score": 0.85},
    )

    assert payload["board_type"] == "weekly_intelligence"
    assert payload["targets"]
    assert payload["delivery_plan"]["channels"]
