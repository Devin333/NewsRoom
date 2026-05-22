from business.memory.memory_metrics import MemoryEvaluationMetrics, MemoryMetric


def test_memory_metric_and_evaluation_metrics_serialize() -> None:
    metric = MemoryMetric("claim_support_rate", 0.9, threshold=0.8, passed=True)
    metrics = MemoryEvaluationMetrics(
        claim_support_rate=0.9,
        recall_usefulness_score=0.8,
        timeline_coverage_score=0.7,
        event_duplicate_rate=0.1,
    )

    assert metric.to_dict()["passed"] is True
    assert 0.0 <= metrics.overall_score() <= 1.0
    assert metrics.to_dict()["overall_score"] == metrics.overall_score()
