from __future__ import annotations

from dataclasses import dataclass, field
import math

from framework.rag.evaluation.report import MetricValue


@dataclass(frozen=True)
class RetrievalMetricCase:
    case_id: str
    gold_evidence_ids: tuple[str, ...]
    ranked_evidence_ids: tuple[str, ...]
    context_evidence_ids: tuple[str, ...] = ()
    gold_source_locators: tuple[str, ...] = ()
    ranked_source_locators: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise ValueError("case_id is required")
        object.__setattr__(self, "gold_evidence_ids", _clean_tuple(self.gold_evidence_ids))
        object.__setattr__(self, "ranked_evidence_ids", _clean_tuple(self.ranked_evidence_ids))
        object.__setattr__(self, "context_evidence_ids", _clean_tuple(self.context_evidence_ids))
        object.__setattr__(self, "gold_source_locators", _clean_tuple(self.gold_source_locators))
        object.__setattr__(self, "ranked_source_locators", _clean_tuple(self.ranked_source_locators))
        object.__setattr__(self, "metadata", dict(self.metadata))


def hit_at_k(case: RetrievalMetricCase, k: int) -> float:
    if k <= 0 or not case.gold_evidence_ids:
        return 0.0
    gold = set(case.gold_evidence_ids)
    return 1.0 if any(item in gold for item in case.ranked_evidence_ids[:k]) else 0.0


def reciprocal_rank(case: RetrievalMetricCase) -> float:
    gold = set(case.gold_evidence_ids)
    if not gold:
        return 0.0
    for index, evidence_id in enumerate(case.ranked_evidence_ids, start=1):
        if evidence_id in gold:
            return 1.0 / index
    return 0.0


def mean_reciprocal_rank(cases: tuple[RetrievalMetricCase, ...]) -> float:
    if not cases:
        return 0.0
    return sum(reciprocal_rank(case) for case in cases) / len(cases)


def ndcg_at_k(case: RetrievalMetricCase, k: int) -> float:
    if k <= 0 or not case.gold_evidence_ids:
        return 0.0
    gold = set(case.gold_evidence_ids)
    dcg = 0.0
    for rank, evidence_id in enumerate(case.ranked_evidence_ids[:k], start=1):
        if evidence_id in gold:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def evidence_coverage(case: RetrievalMetricCase, k: int | None = None) -> float:
    gold = set(case.gold_evidence_ids)
    if not gold:
        return 0.0
    ranked = set(case.ranked_evidence_ids[:k] if k is not None else case.ranked_evidence_ids)
    return len(gold & ranked) / len(gold)


def context_recall(case: RetrievalMetricCase) -> float:
    gold = set(case.gold_evidence_ids)
    if not gold:
        return 0.0
    return len(gold & set(case.context_evidence_ids)) / len(gold)


def source_locator_coverage(case: RetrievalMetricCase, k: int | None = None) -> float:
    gold = set(case.gold_source_locators)
    if not gold:
        return 0.0
    ranked = set(case.ranked_source_locators[:k] if k is not None else case.ranked_source_locators)
    return len(gold & ranked) / len(gold)


def evaluate_retrieval_case(case: RetrievalMetricCase, *, k_values: tuple[int, ...] = (1, 5, 10)) -> tuple[MetricValue, ...]:
    metrics: list[MetricValue] = [
        MetricValue("mrr", reciprocal_rank(case), {"case_id": case.case_id}),
        MetricValue("context_recall", context_recall(case), {"case_id": case.case_id}),
        MetricValue("evidence_coverage", evidence_coverage(case), {"case_id": case.case_id}),
        MetricValue("source_locator_coverage", source_locator_coverage(case), {"case_id": case.case_id}),
    ]
    for k in k_values:
        metrics.append(MetricValue(f"hit_at_{k}", hit_at_k(case, k), {"case_id": case.case_id, "k": k}))
        metrics.append(MetricValue(f"ndcg_at_{k}", ndcg_at_k(case, k), {"case_id": case.case_id, "k": k}))
    return tuple(metrics)


def _clean_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value) for value in values if str(value).strip())


__all__ = [
    "RetrievalMetricCase",
    "context_recall",
    "evaluate_retrieval_case",
    "evidence_coverage",
    "hit_at_k",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "reciprocal_rank",
    "source_locator_coverage",
]
