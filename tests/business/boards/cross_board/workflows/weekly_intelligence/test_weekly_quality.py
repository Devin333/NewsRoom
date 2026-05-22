from __future__ import annotations

from business.boards.cross_board.workflows.weekly_intelligence.weekly_quality import WeeklyQualityBuilder


def test_weekly_quality_builder_reports_coverage_and_weak_spots() -> None:
    result = WeeklyQualityBuilder().build(
        [{"source_urls": ["https://example.com"], "metadata": {}}],
        {"high_confidence_trends": [{"topic": "workflow"}], "weak_signal_trends": []},
    )

    assert result["score"] > 0
    assert result["source_coverage"]["source_url_count"] == 1
    assert result["trend_confidence"]["high_confidence_trend_count"] == 1
