from __future__ import annotations

from framework.rag.evaluation import (
    RetrievalMetricCase,
    evaluate_retrieval_case,
    evidence_coverage,
    hit_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    reciprocal_rank,
    source_locator_coverage,
)


def test_retrieval_metrics_use_generic_evidence_ids():
    case = RetrievalMetricCase(
        case_id="case-1",
        gold_evidence_ids=("gold-1", "gold-2"),
        ranked_evidence_ids=("miss", "gold-2", "gold-1"),
        context_evidence_ids=("gold-1",),
        gold_source_locators=("source://gold-1",),
        ranked_source_locators=("source://miss", "source://gold-1"),
    )

    assert hit_at_k(case, 1) == 0.0
    assert hit_at_k(case, 2) == 1.0
    assert reciprocal_rank(case) == 0.5
    assert round(ndcg_at_k(case, 3), 3) == 0.693
    assert evidence_coverage(case) == 1.0
    assert source_locator_coverage(case) == 1.0
    assert mean_reciprocal_rank((case,)) == 0.5


def test_evaluate_retrieval_case_returns_named_metric_values():
    case = RetrievalMetricCase(
        case_id="case-1",
        gold_evidence_ids=("gold-1",),
        ranked_evidence_ids=("gold-1",),
        context_evidence_ids=("gold-1",),
    )

    metrics = {metric.name: metric.value for metric in evaluate_retrieval_case(case, k_values=(1,))}

    assert metrics["mrr"] == 1.0
    assert metrics["hit_at_1"] == 1.0
    assert metrics["context_recall"] == 1.0
