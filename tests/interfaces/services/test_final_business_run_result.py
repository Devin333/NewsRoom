from __future__ import annotations

from interfaces.services.board_service import BoardWorkflowApplicationService, FinalBusinessRunResult
from tests.business.final_runtime_fixtures import sample_raw_items


def test_final_business_run_result_exposes_runtime_surfaces() -> None:
    result = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())

    assert isinstance(result, FinalBusinessRunResult)
    assert set(result.board_workflow_results) == {
        "ai_news",
        "project_radar",
        "paper_radar",
        "community_pulse",
    }
    assert result.cross_board_result.graph == result.cross_board_graph
    assert result.cross_board_paths == result.cross_board_result.paths
    assert result.cross_board_insights == result.cross_board_result.insights
    assert result.policy_snapshot_refs
    assert result.quality_summary.checks
    assert result.feedback_events
    assert result.learning_signals
    assert result.policy_candidates
    assert result.regression_guard_results
    assert result.artifacts
    assert result.metadata["board_count"] == 4
    assert result.metadata["cross_board_path_count"] == len(result.cross_board_paths)
    assert result.metadata["guard_result_count"] == len(result.regression_guard_results)
    assert result.model_dump(mode="json", exclude_none=True)
