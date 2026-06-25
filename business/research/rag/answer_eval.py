from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from business.research.rag.evidence_eval import EvidenceQAPair


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
    "no evidence",
    "无法确定",
    "无法回答",
    "没有足够证据",
    "证据不足",
    "未提到",
    "没有提到",
    "论文中没有",
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


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

    def abstention_accuracy(self) -> float:
        return _average_optional(score.abstention_correct for score in self.scores)

    def success_rate(self) -> float:
        return sum(1 for score in self.scores if score.answer_success) / self.total if self.total else 0.0

    def report(self) -> str:
        lines = [
            f"=== Evidence Answer Eval (n={self.total}) ===",
            f"  AnswerFactCoverage       = {self.answer_fact_coverage():.3f}",
            f"  CitationGroundingScore   = {self.citation_grounding_score():.3f}",
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
                    f"citations={sub.citation_grounding_score():.3f} "
                    f"success={sub.success_rate():.1%}"
                )
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
        if pair.expected_behavior == "abstain":
            abstention_correct = 1.0 if _looks_like_abstention(sample.answer) else 0.0
            return EvidenceAnswerScores(
                sample=sample,
                fact_coverage=None,
                citation_grounding=None,
                source_locator_grounding=None,
                abstention_correct=abstention_correct,
                answer_success=abstention_correct == 1.0,
            )

        fact_coverage, matched, missing = _fact_coverage(
            sample.answer,
            pair.answer_facts,
            threshold=self._fact_match_threshold,
        )
        citation_grounding = _coverage(sample.cited_chunk_ids, pair.gold_chunk_ids)
        source_locator_grounding = _locator_coverage(
            sample.cited_source_locators,
            pair.gold_source_locators,
        )
        citation_required = bool(pair.gold_chunk_ids)
        citation_passed = (
            not citation_required
            or citation_grounding is not None
            and citation_grounding >= self._success_citation_threshold
        )
        fact_passed = (
            fact_coverage is None
            or fact_coverage >= self._success_fact_threshold
        )
        return EvidenceAnswerScores(
            sample=sample,
            fact_coverage=fact_coverage,
            citation_grounding=citation_grounding,
            source_locator_grounding=source_locator_grounding,
            abstention_correct=None,
            answer_success=fact_passed and citation_passed and not _looks_like_abstention(sample.answer),
            matched_facts=tuple(matched),
            missing_facts=tuple(missing),
        )


def _fact_coverage(
    answer: str,
    facts: list[str],
    *,
    threshold: float,
) -> tuple[float | None, list[str], list[str]]:
    normalized_facts = _unique_texts(facts)
    if not normalized_facts:
        return None, [], []
    matched: list[str] = []
    missing: list[str] = []
    for fact in normalized_facts:
        if _fact_matches(answer, fact, threshold=threshold):
            matched.append(fact)
        else:
            missing.append(fact)
    return len(matched) / len(normalized_facts), matched, missing


def _fact_matches(answer: str, fact: str, *, threshold: float) -> bool:
    normalized_answer = _normalize_text(answer)
    normalized_fact = _normalize_text(fact)
    if not normalized_answer or not normalized_fact:
        return False
    if normalized_fact in normalized_answer:
        return True
    fact_tokens = _tokens(normalized_fact)
    if not fact_tokens:
        return False
    answer_tokens = set(_tokens(normalized_answer))
    overlap = sum(1 for token in fact_tokens if token in answer_tokens)
    return overlap / len(fact_tokens) >= threshold


def _coverage(retrieved: list[str], required: list[str]) -> float | None:
    required_set = set(_unique_texts(required))
    if not required_set:
        return None
    return len(required_set.intersection(_unique_texts(retrieved))) / len(required_set)


def _locator_coverage(retrieved: list[str], required: list[str]) -> float | None:
    required_locators = _unique_texts(required)
    if not required_locators:
        return None
    retrieved_locators = _unique_texts(retrieved)
    hits = 0
    for locator in required_locators:
        if any(_locator_matches(candidate, locator) for candidate in retrieved_locators):
            hits += 1
    return hits / len(required_locators)


def _locator_matches(candidate: str, required: str) -> bool:
    return bool(candidate and required) and (
        candidate == required
        or candidate.startswith(required)
        or required.startswith(candidate)
    )


def _looks_like_abstention(answer: str) -> bool:
    normalized = _normalize_text(answer)
    return any(marker in normalized for marker in _ABSTAIN_MARKERS)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


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
