from __future__ import annotations

from business.boards.cross_board.workflows.weekly_intelligence.weekly_historian import WeeklyHistorian


def test_weekly_historian_builds_timeline_and_delta() -> None:
    result = WeeklyHistorian().build(
        [
            {"finished_at": "2026-05-01T00:00:00Z", "report_id": "r1", "title": "one", "quality_score": 0.5},
            {"finished_at": "2026-05-02T00:00:00Z", "report_id": "r2", "title": "two", "quality_score": 0.8},
        ],
        {"recurring_entities": [{"entity": "OpenAI"}], "emerging_topics": [{"topic": "workflow"}]},
    )

    assert len(result["timeline"]) == 2
    assert result["repeated_themes"] == ["OpenAI"]
    assert result["significance_delta"] == 0.3
