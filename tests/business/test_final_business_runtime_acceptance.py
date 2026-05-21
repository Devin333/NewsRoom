from __future__ import annotations

from interfaces.services.board_service import BoardWorkflowApplicationService
from tests.business.final_runtime_fixtures import sample_raw_items


def test_final_business_runtime_acceptance_surfaces_are_complete() -> None:
    result = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())

    for board_type, workflow_result in result.board_workflow_results.items():
        assert workflow_result.result.cards, board_type
        assert workflow_result.trace.run_id == workflow_result.result.run_id
        assert workflow_result.trace.card_count == len(workflow_result.result.cards)
        assert workflow_result.metadata["board_type"] == board_type
        assert workflow_result.artifact_refs
        assert workflow_result.feedback_events is not None
        assert workflow_result.learning_signals is not None
        assert workflow_result.policy_candidates is not None
        assert workflow_result.guard_results is not None

    assert result.cross_board_graph.nodes
    assert result.cross_board_paths
    assert all(path.metadata.get("scoring_result") for path in result.cross_board_paths)
    assert result.cross_board_insights
    assert all(candidate.metadata.get("scoring_result") for candidate in result.cross_board_insights)
    assert result.quality_summary.status in {"passed", "warning", "failed", "unchecked"}
    assert result.feedback_events
    assert result.learning_signals
    assert result.policy_candidates
    assert result.regression_guard_results
    assert result.metadata["feedback_count"] == len(result.feedback_events)
    assert result.metadata["learning_signal_count"] == len(result.learning_signals)
    assert result.metadata["policy_candidate_count"] == len(result.policy_candidates)
