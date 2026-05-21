from __future__ import annotations

from business.evaluation import BusinessRunEvaluator, RankingEvaluationCase
from interfaces.services.board_service import BoardWorkflowApplicationService
from tests.business.final_runtime_fixtures import sample_raw_items


def test_business_run_evaluator_evaluates_ranking_case() -> None:
    result = BusinessRunEvaluator().evaluate_ranking(
        RankingEvaluationCase(expected_ids=["a", "b"], actual_ids=["x", "a", "b"]),
        k=2,
        threshold=0.4,
    )

    assert result.subject_type == "ranking"
    assert result.metric("precision@2") is not None
    assert result.metric("recall@2") is not None
    assert result.score > 0.0


def test_business_run_evaluator_evaluates_final_run() -> None:
    final_run = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())

    result = BusinessRunEvaluator().evaluate_final_run(final_run)

    assert result.subject_type == "final_business_run"
    assert result.metric("quality_pass_rate") is not None
    assert result.metric("path_stage_completeness") is not None
    assert result.metric("memory_hit_rate") is not None
    assert result.metadata["board_count"] == 4
    assert result.to_dict()["metrics"]
