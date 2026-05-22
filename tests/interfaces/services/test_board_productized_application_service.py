from __future__ import annotations

import pytest

from framework.specs import WorkflowStatus

from interfaces.services.board_service import BoardApplicationService
from business.evaluation.fixtures import sample_signal


def test_board_application_service_runs_productized_board(tmp_path) -> None:
    result = BoardApplicationService().run_board(
        "ai_news",
        [sample_signal("ai_news")],
        topic="Agent Memory",
        run_id="interface-ai-news",
        artifact_root=tmp_path,
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["subscription_payload"]["targets"]


def test_board_application_service_runs_all_productized_boards(tmp_path) -> None:
    results = BoardApplicationService().run_all_boards(
        [
            sample_signal("ai_news"),
            sample_signal("github_project"),
            sample_signal("paper"),
            sample_signal("community_discussion"),
        ],
        topic="Agent Memory",
        run_id_prefix="interface-all",
        artifact_root=tmp_path,
    )

    assert set(results) == {"ai_news", "project_radar", "paper_radar", "community_pulse"}
    assert all(result.status == WorkflowStatus.SUCCEEDED for result in results.values())


def test_board_application_service_rejects_invalid_productized_board(tmp_path) -> None:
    with pytest.raises(ValueError):
        BoardApplicationService().run_board(
            "cross_board",
            [sample_signal("ai_news")],
            artifact_root=tmp_path,
        )


def test_board_application_service_builds_productized_cross_board_output() -> None:
    result = BoardApplicationService().build_productized_cross_board_output(
        [
            sample_signal("ai_news"),
            sample_signal("github_project"),
            sample_signal("paper"),
            sample_signal("community_discussion"),
        ],
        topic="Agent Memory",
    )

    assert result["board_payloads"]["ai_news"]["cards"]
    assert result["subscription_payload"]["targets"]
    assert "improvement_report" in result
