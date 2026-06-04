from __future__ import annotations

from business.research.benchmark import (
    ResearchBenchmark,
    ResearchDataset,
    ResearchMetric,
    ResearchSOTAClaim,
    ResearchScore,
    validate_benchmark_score_refs,
    validate_sota_claim_status,
)


def test_benchmark_score_requires_metric_dataset_and_paper_refs() -> None:
    benchmark = ResearchBenchmark(benchmark_id="mmlu", name="MMLU", task="reasoning", dataset_ids=["mmlu"])
    dataset = ResearchDataset(dataset_id="mmlu", name="MMLU", source_refs=["paper://paper-1/sec-exp"])
    metric = ResearchMetric(metric_id="accuracy", name="Accuracy")
    score = ResearchScore(
        score_id="score-1",
        paper_id="paper-1",
        benchmark_id=benchmark.benchmark_id,
        dataset_id=dataset.dataset_id,
        metric_id=metric.metric_id,
        value=87.5,
        source_refs=["paper://paper-1/sec-exp"],
    )
    claim = ResearchSOTAClaim(
        claim_id="sota-1",
        paper_id="paper-1",
        benchmark_id=benchmark.benchmark_id,
        dataset_id=dataset.dataset_id,
        metric_id=metric.metric_id,
        score_id=score.score_id,
        claim_text="The method reaches a new SOTA.",
        verification_status="verified",
        source_refs=["paper://paper-1/sec-exp"],
    )

    assert score.to_dict()["metric_id"] == "accuracy"
    assert validate_benchmark_score_refs(score).passed is True
    assert validate_sota_claim_status(claim).passed is True
