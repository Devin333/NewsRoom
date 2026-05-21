from __future__ import annotations

import math

from business.evaluation.models import RankingEvaluationCase, clamp_metric


def precision_at_k(actual_ids: list[str], relevant_ids: set[str] | list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    relevant = {str(item) for item in relevant_ids}
    if not relevant:
        return 0.0
    selected = [str(item) for item in actual_ids[:k]]
    return clamp_metric(len([item for item in selected if item in relevant]) / k)


def recall_at_k(actual_ids: list[str], relevant_ids: set[str] | list[str], k: int) -> float:
    relevant = {str(item) for item in relevant_ids}
    if not relevant:
        return 0.0
    selected = {str(item) for item in actual_ids[: max(0, k)]}
    return clamp_metric(len(selected & relevant) / len(relevant))


def mean_reciprocal_rank(actual_ids: list[str], relevant_ids: set[str] | list[str]) -> float:
    relevant = {str(item) for item in relevant_ids}
    for index, item in enumerate(actual_ids, start=1):
        if str(item) in relevant:
            return clamp_metric(1.0 / index)
    return 0.0


def ndcg_at_k(actual_ids: list[str], relevance: dict[str, float], k: int) -> float:
    if k <= 0:
        return 0.0
    gains = [float(relevance.get(str(item), 0.0)) for item in actual_ids[:k]]
    dcg = _discounted_gain(gains)
    ideal = _discounted_gain(sorted((float(value) for value in relevance.values()), reverse=True)[:k])
    if ideal <= 0.0:
        return 0.0
    return clamp_metric(dcg / ideal)


def ranking_metrics(case: RankingEvaluationCase, *, k: int = 10) -> dict[str, float]:
    relevant = set(case.expected_ids)
    relevance = case.relevance or {identifier: 1.0 for identifier in case.expected_ids}
    return {
        f"precision@{k}": precision_at_k(case.actual_ids, relevant, k),
        f"recall@{k}": recall_at_k(case.actual_ids, relevant, k),
        "mrr": mean_reciprocal_rank(case.actual_ids, relevant),
        f"ndcg@{k}": ndcg_at_k(case.actual_ids, relevance, k),
    }


def _discounted_gain(gains: list[float]) -> float:
    return sum((2.0 ** gain - 1.0) / math.log2(index + 2.0) for index, gain in enumerate(gains))
