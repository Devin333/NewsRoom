from __future__ import annotations

from business.evaluation.memory_metrics import memory_metrics
from business.evaluation.models import BusinessEvaluationResult, EvaluationMetricResult, RankingEvaluationCase
from business.evaluation.path_metrics import cross_board_path_metrics
from business.evaluation.quality_metrics import quality_metrics
from business.evaluation.ranking_metrics import ranking_metrics


class BusinessRunEvaluator:
    def evaluate_ranking(
        self,
        case: RankingEvaluationCase,
        *,
        k: int = 10,
        threshold: float = 0.5,
    ) -> BusinessEvaluationResult:
        metrics = [
            EvaluationMetricResult.create(name, score, threshold=threshold)
            for name, score in ranking_metrics(case, k=k).items()
        ]
        return BusinessEvaluationResult(
            subject_id="ranking",
            subject_type="ranking",
            metrics=metrics,
            metadata={"k": k, "expected_count": len(case.expected_ids), "actual_count": len(case.actual_ids)},
        )

    def evaluate_cross_board_paths(self, paths: list[object]) -> BusinessEvaluationResult:
        metrics = [
            EvaluationMetricResult.create(name, score, threshold=0.5)
            for name, score in cross_board_path_metrics(paths).items()
        ]
        return BusinessEvaluationResult(
            subject_id="cross_board_paths",
            subject_type="cross_board_paths",
            metrics=metrics,
            metadata={"path_count": len(paths)},
        )

    def evaluate_board_cards(self, board_type: str, cards: list[object]) -> BusinessEvaluationResult:
        metrics = [
            EvaluationMetricResult.create(name, score, threshold=0.0)
            for name, score in memory_metrics(cards).items()
        ]
        return BusinessEvaluationResult(
            subject_id=board_type,
            subject_type="board_cards",
            metrics=metrics,
            metadata={"card_count": len(cards)},
        )

    def evaluate_final_run(self, final_run: object) -> BusinessEvaluationResult:
        board_cards = [
            card
            for workflow_result in getattr(final_run, "board_workflow_results", {}).values()
            for card in getattr(getattr(workflow_result, "result", None), "cards", []) or []
        ]
        metric_values = {
            **quality_metrics(
                getattr(final_run, "quality_summary", None),
                list(getattr(final_run, "feedback_events", []) or []),
            ),
            **cross_board_path_metrics(list(getattr(final_run, "cross_board_paths", []) or [])),
            **memory_metrics(board_cards),
        }
        metrics = [
            EvaluationMetricResult.create(name, score, threshold=_threshold_for(name))
            for name, score in metric_values.items()
        ]
        return BusinessEvaluationResult(
            subject_id=str(getattr(final_run, "metadata", {}).get("run_id", "final_business_run")),
            subject_type="final_business_run",
            metrics=metrics,
            metadata={
                "board_count": len(getattr(final_run, "board_workflow_results", {}) or {}),
                "path_count": len(getattr(final_run, "cross_board_paths", []) or []),
                "card_count": len(board_cards),
            },
        )


def _threshold_for(metric_name: str) -> float:
    if metric_name in {"memory_hit_rate", "memory_decision_impact"}:
        return 0.0
    if metric_name == "contradiction_block_rate":
        return 1.0
    return 0.5
