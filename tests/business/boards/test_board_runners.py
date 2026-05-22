from __future__ import annotations

import pytest

from framework.specs import WorkflowStatus

from business.boards._runner import runner_for_board_type
from business.evaluation.fixtures import sample_signal


@pytest.mark.parametrize("board_type", ["ai_news", "project_radar", "paper_radar", "community_pulse"])
def test_productized_board_runner_executes_offline(board_type: str, tmp_path) -> None:
    signals = [
        sample_signal("ai_news"),
        sample_signal("github_project"),
        sample_signal("paper"),
        sample_signal("community_discussion"),
    ]

    result = runner_for_board_type(board_type, artifact_root=tmp_path).run(
        signals=signals,
        topic="Agent Memory",
        run_id=f"runner-{board_type}",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["cards"]
    assert result.output["quality_summary"]["score"] is not None
    assert result.output["subscription_payload"]["targets"]
    assert result.output["feedback_events"] is not None
    assert result.output["improvement_recommendations"] is not None
