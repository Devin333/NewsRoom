from __future__ import annotations

from business.boards.cross_board.cross_board_improvement import CrossBoardImprovementService


def test_cross_board_improvement_prioritizes_recommendations() -> None:
    result = CrossBoardImprovementService().aggregate(
        {
            "ai_news": {"improvement_recommendations": [{"recommendation_id": "low", "severity": "info"}]},
            "paper_radar": {"improvement_recommendations": [{"recommendation_id": "high", "severity": "error"}]},
        }
    )

    assert result["priority_order"][0] == "high"
    assert result["next_actions"]
