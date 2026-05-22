from __future__ import annotations

from business.boards._runner import runner_for_board_type
from business.boards.cross_board.intelligence_service import CrossBoardIntelligenceService
from tests.fixtures.business.productized_signals import (
    sample_ai_news_productized_signals,
    sample_community_pulse_productized_signals,
    sample_paper_radar_productized_signals,
    sample_project_radar_productized_signals,
)


BOARD_FIXTURES = {
    "ai_news": sample_ai_news_productized_signals,
    "project_radar": sample_project_radar_productized_signals,
    "paper_radar": sample_paper_radar_productized_signals,
    "community_pulse": sample_community_pulse_productized_signals,
}


def test_cross_board_productized_acceptance(tmp_path) -> None:
    board_outputs = {}
    for board_type, fixture in BOARD_FIXTURES.items():
        result = runner_for_board_type(board_type, artifact_root=tmp_path).run(
            signals=fixture(),
            topic="Agent Memory",
            run_id=f"cross-accept-{board_type}",
        )
        board_outputs[board_type] = result.output

    output = CrossBoardIntelligenceService().build(board_outputs, topic="Agent Memory")

    assert output["cross_board_summary"]
    assert "shared_entities" in output
    assert output["shared_trends"]
    assert "conflicting_signals" in output
    assert set(output["board_coverage"]) == set(BOARD_FIXTURES)
    assert isinstance(output["recommendations"], list)
    assert output["subscription_payload"]["targets"]
    assert output["improvement_report"]["reports"]

    tags = {
        tag
        for target in output["subscription_payload"]["targets"]
        for tag in target.get("tags", [])
    }
    assert {"ai_news", "github", "paper", "community"} <= tags
    assert len(output["improvement_report"]["reports"]) == 4
