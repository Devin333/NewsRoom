from __future__ import annotations

from business.boards.cross_board.workflows.weekly_intelligence.weekly_improvement import WeeklyImprovementBuilder


def test_weekly_improvement_builder_creates_recommendations_from_quality() -> None:
    result = WeeklyImprovementBuilder().build(
        {"weak_spots": ["missing_source_urls"]},
        {"weak_signal_trends": []},
    )

    assert result["recommendations"]
    assert result["risks"]
