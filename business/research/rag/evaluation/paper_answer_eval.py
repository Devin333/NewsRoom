from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair
from framework.rag.evaluation import AnswerMetricCase, score_answer_case


_ABSTAIN_MARKERS = (
    "cannot determine",
    "cannot answer",
    "does not contain",
    "does not discuss",
    "insufficient evidence",
    "not enough evidence",
    "not stated",
    "not discussed",
    "not mentioned",
    "does not mention",
    "does not include",
    "do not mention",
    "do not discuss",
    "do not include",
    "not in the provided context",
    "not available from the passages",
    "provided context does not mention",
    "context does not mention",
    "no evidence",
    "无法确定",
    "无法回答",
    "没有足够证据",
    "证据不足",
    "未提到",
    "没有提到",
    "论文中没有",
)


@dataclass
class EvidenceAnswerSample:
    pair: EvidenceQAPair
    answer: str
    cited_chunk_ids: list[str] = field(default_factory=list)
    cited_source_locators: list[str] = field(default_factory=list)
    context_chunk_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceAnswerScores:
    sample: EvidenceAnswerSample
    fact_coverage: float | None
    citation_grounding: float | None
    source_locator_grounding: float | None
    abstention_correct: float | None
    answer_success: bool
    retrieval_context_coverage: float | None = None
    citation_gold_coverage: float | None = None
    failure_reason: str = ""
    matched_facts: tuple[str, ...] = ()
    missing_facts: tuple[str, ...] = ()

    @property
    def qa_type(self) -> str:
        return self.sample.pair.qa_type


@dataclass
class EvidenceAnswerEvalResult:
    scores: list[EvidenceAnswerScores] = field(default_factory=list)
    by_qa_type: dict[str, "EvidenceAnswerEvalResult"] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.scores)

    def answer_fact_coverage(self) -> float:
        return _average_optional(score.fact_coverage for score in self.scores)

    def citation_grounding_score(self) -> float:
        return _average_optional(score.citation_grounding for score in self.scores)

    def source_locator_grounding_score(self) -> float:
        return _average_optional(score.source_locator_grounding for score in self.scores)

    def retrieval_context_coverage_score(self) -> float:
        return _average_optional(score.retrieval_context_coverage for score in self.scores)

    def citation_gold_coverage_score(self) -> float:
        return _average_optional(score.citation_gold_coverage for score in self.scores)

    def abstention_accuracy(self) -> float:
        return _average_optional(score.abstention_correct for score in self.scores)

    def success_rate(self) -> float:
        return sum(1 for score in self.scores if score.answer_success) / self.total if self.total else 0.0

    def failure_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for score in self.scores:
            reason = score.failure_reason
            if not reason:
                continue
            counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))

    def report(self) -> str:
        lines = [
            f"=== Evidence Answer Eval (n={self.total}) ===",
            f"  AnswerFactCoverage       = {self.answer_fact_coverage():.3f}",
            f"  RetrievalContextCoverage = {self.retrieval_context_coverage_score():.3f}",
            f"  CitationGroundingScore   = {self.citation_grounding_score():.3f}",
            f"  CitationGoldCoverage     = {self.citation_gold_coverage_score():.3f}",
            f"  SourceLocatorGrounding   = {self.source_locator_grounding_score():.3f}",
            f"  AbstentionAccuracy       = {self.abstention_accuracy():.3f}",
            f"  AnswerSuccessRate        = {self.success_rate():.1%}",
        ]
        if self.by_qa_type:
            lines.append("  -- by qa_type --")
            for qa_type in sorted(self.by_qa_type):
                sub = self.by_qa_type[qa_type]
                lines.append(
                    f"     {qa_type:<18} n={sub.total:<3} "
                    f"facts={sub.answer_fact_coverage():.3f} "
                    f"context={sub.retrieval_context_coverage_score():.3f} "
                    f"citations={sub.citation_grounding_score():.3f} "
                    f"success={sub.success_rate():.1%}"
                )
        failure_counts = self.failure_reason_counts()
        if failure_counts:
            lines.append("  -- failure reasons --")
            for reason, count in failure_counts.items():
                lines.append(f"     {reason:<32} n={count}")
        return "\n".join(lines)


class EvidenceAnswerEvaluator:
    """Deterministic answer-level evaluation for evidence QA benchmarks."""

    def __init__(
        self,
        *,
        fact_match_threshold: float = 0.75,
        success_fact_threshold: float = 0.8,
        success_citation_threshold: float = 0.5,
    ) -> None:
        self._fact_match_threshold = fact_match_threshold
        self._success_fact_threshold = success_fact_threshold
        self._success_citation_threshold = success_citation_threshold

    def evaluate(self, samples: list[EvidenceAnswerSample]) -> EvidenceAnswerEvalResult:
        scores = [self.score(sample) for sample in samples]
        result = EvidenceAnswerEvalResult(scores=scores)
        by_type: dict[str, list[EvidenceAnswerScores]] = {}
        for score in scores:
            by_type.setdefault(score.qa_type, []).append(score)
        result.by_qa_type = {
            qa_type: EvidenceAnswerEvalResult(scores=type_scores)
            for qa_type, type_scores in by_type.items()
        }
        return result

    def score(self, sample: EvidenceAnswerSample) -> EvidenceAnswerScores:
        pair = sample.pair
        score = score_answer_case(
            _metric_case_from_sample(sample),
            fact_match_threshold=self._fact_match_threshold,
            success_fact_threshold=self._success_fact_threshold,
            success_citation_threshold=self._success_citation_threshold,
            abstain_markers=_ABSTAIN_MARKERS,
        )
        return EvidenceAnswerScores(
            sample=sample,
            fact_coverage=score.fact_coverage,
            citation_grounding=score.citation_grounding,
            source_locator_grounding=score.source_locator_grounding,
            abstention_correct=score.abstention_correct,
            answer_success=score.answer_success,
            retrieval_context_coverage=score.retrieval_context_coverage,
            citation_gold_coverage=score.citation_gold_coverage,
            failure_reason=score.failure_reason,
            matched_facts=score.matched_facts,
            missing_facts=score.missing_facts,
        )


def _metadata_ids(metadata: dict[str, Any], key: str) -> list[str]:
    raw = metadata.get(key)
    if not isinstance(raw, list):
        return []
    return _unique_texts(raw)


def _metric_case_from_sample(sample: EvidenceAnswerSample) -> AnswerMetricCase:
    pair = sample.pair
    return AnswerMetricCase(
        case_id=f"{pair.paper_id}:{pair.qa_type}:{pair.question}",
        question=pair.question,
        answer=sample.answer,
        expected_facts=tuple(pair.answer_facts),
        cited_evidence_ids=tuple(sample.cited_chunk_ids),
        context_evidence_ids=tuple(sample.context_chunk_ids),
        gold_evidence_ids=tuple(pair.gold_chunk_ids),
        expected_abstain=pair.expected_behavior == "abstain",
        cited_source_locators=tuple(sample.cited_source_locators),
        gold_source_locators=tuple(pair.gold_source_locators),
        retrieved_evidence_ids=tuple(_metadata_ids(sample.metadata, "retrieved_chunk_ids")),
        metadata={
            "paper_id": pair.paper_id,
            "qa_type": pair.qa_type,
            **dict(sample.metadata),
        },
    )


def _unique_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def _average_optional(values: Any) -> float:
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else 0.0


__all__ = [
    "EvidenceAnswerEvalResult",
    "EvidenceAnswerEvaluator",
    "EvidenceAnswerSample",
    "EvidenceAnswerScores",
]
