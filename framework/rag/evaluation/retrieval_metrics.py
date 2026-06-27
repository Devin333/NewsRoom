from __future__ import annotations

from dataclasses import dataclass, field
import math

from framework.rag.evaluation.report import MetricValue


@dataclass(frozen=True)
class RetrievalMetricCase:
    case_id: str
    gold_evidence_ids: tuple[str, ...]
    ranked_evidence_ids: tuple[str, ...]
    ranked_evidence_id_candidates: tuple[tuple[str, ...], ...] = ()
    context_evidence_ids: tuple[str, ...] = ()
    gold_source_locators: tuple[str, ...] = ()
    ranked_source_locators: tuple[str, ...] = ()
    ranked_source_locator_candidates: tuple[tuple[str, ...], ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise ValueError("case_id is required")
        object.__setattr__(self, "gold_evidence_ids", _clean_tuple(self.gold_evidence_ids))
        object.__setattr__(self, "ranked_evidence_ids", _clean_tuple(self.ranked_evidence_ids))
        object.__setattr__(
            self,
            "ranked_evidence_id_candidates",
            _clean_tuple_groups(self.ranked_evidence_id_candidates),
        )
        object.__setattr__(self, "context_evidence_ids", _clean_tuple(self.context_evidence_ids))
        object.__setattr__(self, "gold_source_locators", _clean_tuple(self.gold_source_locators))
        object.__setattr__(self, "ranked_source_locators", _clean_tuple(self.ranked_source_locators))
        object.__setattr__(
            self,
            "ranked_source_locator_candidates",
            _clean_tuple_groups(self.ranked_source_locator_candidates),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))


def hit_at_k(case: RetrievalMetricCase, k: int) -> float:
    if k <= 0 or not case.gold_evidence_ids:
        return 0.0
    gold = set(case.gold_evidence_ids)
    return 1.0 if any(gold.intersection(group) for group in _ranked_evidence_groups(case)[:k]) else 0.0


def reciprocal_rank(case: RetrievalMetricCase) -> float:
    gold = set(case.gold_evidence_ids)
    if not gold:
        return 0.0
    for index, group in enumerate(_ranked_evidence_groups(case), start=1):
        if gold.intersection(group):
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
    seen_hits: set[str] = set()
    dcg = 0.0
    ranked_groups = _ranked_evidence_groups(case)[:k]
    for rank, group in enumerate(ranked_groups, start=1):
        new_hits = gold.intersection(group) - seen_hits
        if new_hits:
            dcg += 1.0 / math.log2(rank + 1)
            seen_hits.add(sorted(new_hits)[0])
    ideal_hits = min(len(gold), len(ranked_groups))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def evidence_coverage(case: RetrievalMetricCase, k: int | None = None) -> float:
    gold = set(case.gold_evidence_ids)
    if not gold:
        return 0.0
    ranked_groups = _ranked_evidence_groups(case)
    if k is not None:
        ranked_groups = ranked_groups[:k]
    ranked = {candidate for group in ranked_groups for candidate in group}
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
    ranked_groups = _ranked_source_locator_groups(case)
    if k is not None:
        ranked_groups = ranked_groups[:k]
    candidates = [locator for group in ranked_groups for locator in group]
    hits = sum(1 for locator in gold if any(_locator_matches(candidate, locator) for candidate in candidates))
    return hits / len(gold)


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


def _clean_tuple_groups(values: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    for group in values:
        cleaned = _clean_tuple(group)
        if cleaned:
            groups.append(cleaned)
    return tuple(groups)


def _ranked_evidence_groups(case: RetrievalMetricCase) -> tuple[tuple[str, ...], ...]:
    if case.ranked_evidence_id_candidates:
        return case.ranked_evidence_id_candidates
    return tuple((evidence_id,) for evidence_id in case.ranked_evidence_ids)


def _ranked_source_locator_groups(case: RetrievalMetricCase) -> tuple[tuple[str, ...], ...]:
    if case.ranked_source_locator_candidates:
        return case.ranked_source_locator_candidates
    return tuple((locator,) for locator in case.ranked_source_locators)


def _locator_matches(candidate: str, required: str) -> bool:
    if not candidate or not required:
        return False
    return candidate == required or candidate.startswith(required) or required.startswith(candidate)


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
