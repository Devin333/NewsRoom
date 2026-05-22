from __future__ import annotations

from business.boards.cross_board.workflows.weekly_intelligence.trend_analyzer import WeeklyTrendAnalyzer


def test_weekly_trend_analyzer_extracts_trend_sections() -> None:
    result = WeeklyTrendAnalyzer().analyze(
        [
            {"title": "OpenAI Agent Memory workflow", "sections": [{"content": "Agent Memory workflow evidence"}], "quality_score": 0.9},
            {"title": "OpenAI Agent Memory benchmark", "sections": [{"content": "benchmark evaluation"}], "quality_score": 0.9},
        ]
    )

    assert result["recurring_entities"]
    assert result["emerging_topics"]
    assert result["high_confidence_trends"]
