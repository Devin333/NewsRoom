from __future__ import annotations

from business.boards.final_run_builder import FinalBusinessRunBuilder
from interfaces.services.board_service import BoardWorkflowApplicationService, FinalBusinessRunResult
from tests.business.final_runtime_fixtures import sample_raw_items


def test_final_business_run_builder_preserves_result_shape() -> None:
    service = BoardWorkflowApplicationService()
    workflow_results = service.run_all_board_workflows(sample_raw_items())
    cross_board_result = service.run_cross_board_graph_intelligence(sample_raw_items()).result

    result = FinalBusinessRunBuilder(FinalBusinessRunResult).build(
        workflow_results,
        cross_board_result,
    )

    assert isinstance(result, FinalBusinessRunResult)
    assert result.board_workflow_results == workflow_results
    assert result.cross_board_result == cross_board_result
    assert result.cross_board_graph == cross_board_result.graph
    assert result.cross_board_paths == cross_board_result.paths
    assert result.cross_board_insights == cross_board_result.insights
    assert result.metadata["board_count"] == len(workflow_results)
    assert result.metadata["cross_board_path_count"] == len(cross_board_result.paths)
    assert result.metadata["feedback_count"] == len(result.feedback_events)
    assert result.metadata["learning_signal_count"] == len(result.learning_signals)
    assert result.metadata["policy_candidate_count"] == len(result.policy_candidates)
    assert result.metadata["guard_result_count"] == len(result.regression_guard_results)
