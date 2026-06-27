from __future__ import annotations

from dataclasses import dataclass, field
import re

from framework.rag.evaluation.report import MetricValue


@dataclass(frozen=True)
class AnswerMetricCase:
    case_id: str
    question: str
    answer: str
    expected_facts: tuple[str, ...] = ()
    cited_evidence_ids: tuple[str, ...] = ()
    context_evidence_ids: tuple[str, ...] = ()
    gold_evidence_ids: tuple[str, ...] = ()
    expected_abstain: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise ValueError("case_id is required")
        object.__setattr__(self, "question", str(self.question or ""))
        object.__setattr__(self, "answer", str(self.answer or ""))
        object.__setattr__(self, "expected_facts", _clean_tuple(self.expected_facts))
        object.__setattr__(self, "cited_evidence_ids", _clean_tuple(self.cited_evidence_ids))
        object.__setattr__(self, "context_evidence_ids", _clean_tuple(self.context_evidence_ids))
        object.__setattr__(self, "gold_evidence_ids", _clean_tuple(self.gold_evidence_ids))
        object.__setattr__(self, "metadata", dict(self.metadata))


def fact_coverage(case: AnswerMetricCase) -> float:
    if not case.expected_facts:
        return 1.0
    answer = _normalize(case.answer)
    matched = sum(1 for fact in case.expected_facts if _normalize(fact) in answer)
    return matched / len(case.expected_facts)


def citation_grounding(case: AnswerMetricCase) -> float:
    if not case.cited_evidence_ids:
        return 0.0
    allowed = set(case.context_evidence_ids) | set(case.gold_evidence_ids)
    if not allowed:
        return 0.0
    grounded = sum(1 for citation in case.cited_evidence_ids if citation in allowed)
    return grounded / len(case.cited_evidence_ids)


def answer_relevance(case: AnswerMetricCase) -> float:
    question_terms = _token_set(case.question)
    if not question_terms:
        return 0.0
    answer_terms = _token_set(case.answer)
    return len(question_terms & answer_terms) / len(question_terms)


def faithfulness_proxy(case: AnswerMetricCase) -> float:
    if _is_abstention(case.answer):
        return 1.0 if case.expected_abstain else 0.0
    return fact_coverage(case) * citation_grounding(case)


def abstention_accuracy(case: AnswerMetricCase) -> float:
    abstained = _is_abstention(case.answer)
    return 1.0 if abstained == case.expected_abstain else 0.0


def evaluate_answer_case(case: AnswerMetricCase) -> tuple[MetricValue, ...]:
    return (
        MetricValue("fact_coverage", fact_coverage(case), {"case_id": case.case_id}),
        MetricValue("citation_grounding", citation_grounding(case), {"case_id": case.case_id}),
        MetricValue("answer_relevance", answer_relevance(case), {"case_id": case.case_id}),
        MetricValue("faithfulness_proxy", faithfulness_proxy(case), {"case_id": case.case_id}),
        MetricValue("abstention_accuracy", abstention_accuracy(case), {"case_id": case.case_id}),
    )


def _clean_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value) for value in values if str(value).strip())


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _token_set(text: str) -> set[str]:
    return {match.group(0).casefold() for match in re.finditer(r"[A-Za-z0-9_]+", str(text or ""))}


def _is_abstention(answer: str) -> bool:
    text = _normalize(answer)
    return any(marker in text for marker in ("insufficient evidence", "not enough evidence", "cannot answer"))


__all__ = [
    "AnswerMetricCase",
    "abstention_accuracy",
    "answer_relevance",
    "citation_grounding",
    "evaluate_answer_case",
    "fact_coverage",
    "faithfulness_proxy",
]
