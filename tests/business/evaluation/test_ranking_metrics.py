from __future__ import annotations

from business.evaluation import (
    RankingEvaluationCase,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    ranking_metrics,
    recall_at_k,
)


def test_ranking_metrics_are_deterministic() -> None:
    actual = ["a", "x", "b", "c"]
    relevant = {"a", "b", "c"}

    assert precision_at_k(actual, relevant, 2) == 0.5
    assert recall_at_k(actual, relevant, 2) == 0.3333
    assert mean_reciprocal_rank(actual, relevant) == 1.0
    assert ndcg_at_k(actual, {"a": 1.0, "b": 0.8, "c": 0.5}, 3) > 0.0


def test_ranking_metrics_bundle_uses_case_relevance() -> None:
    case = RankingEvaluationCase(
        expected_ids=["a", "b"],
        actual_ids=["x", "b", "a"],
        relevance={"a": 1.0, "b": 0.5},
    )

    metrics = ranking_metrics(case, k=2)

    assert metrics["precision@2"] == 0.5
    assert metrics["recall@2"] == 0.5
    assert metrics["mrr"] == 0.5
    assert 0.0 <= metrics["ndcg@2"] <= 1.0
