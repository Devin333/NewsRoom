from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
import re

from framework.rag.evaluation.report import MetricValue


DEFAULT_ABSTAIN_MARKERS = (
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
    "provided passages do not mention",
    "context does not mention",
    "no evidence",
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_STRUCTURAL_FACT_STOPWORDS = {
    "figure",
    "fig",
    "table",
    "tbl",
    "equation",
    "eq",
    "caption",
    "nearby",
    "context",
    "source",
    "section",
    "latex",
    "normalized",
    "symbols",
    "operators",
    "begin",
    "end",
    "label",
    "mathcal",
    "sigma",
    "text",
    "theta",
    "a",
    "an",
    "and",
    "are",
    "as",
    "for",
    "in",
    "is",
    "of",
    "on",
    "our",
    "the",
    "this",
    "to",
    "use",
    "we",
    "with",
}


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
    cited_source_locators: tuple[str, ...] = ()
    gold_source_locators: tuple[str, ...] = ()
    retrieved_evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise ValueError("case_id is required")
        object.__setattr__(self, "question", str(self.question or ""))
        object.__setattr__(self, "answer", str(self.answer or ""))
        object.__setattr__(self, "expected_facts", _clean_tuple(self.expected_facts))
        object.__setattr__(self, "cited_evidence_ids", _clean_tuple(self.cited_evidence_ids))
        object.__setattr__(self, "context_evidence_ids", _clean_tuple(self.context_evidence_ids))
        object.__setattr__(self, "gold_evidence_ids", _clean_tuple(self.gold_evidence_ids))
        object.__setattr__(self, "cited_source_locators", _clean_tuple(self.cited_source_locators))
        object.__setattr__(self, "gold_source_locators", _clean_tuple(self.gold_source_locators))
        object.__setattr__(self, "retrieved_evidence_ids", _clean_tuple(self.retrieved_evidence_ids))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class AnswerMetricScore:
    case: AnswerMetricCase
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


def score_answer_case(
    case: AnswerMetricCase,
    *,
    fact_match_threshold: float = 0.75,
    success_fact_threshold: float = 0.8,
    success_citation_threshold: float = 0.5,
    abstain_markers: Sequence[str] = DEFAULT_ABSTAIN_MARKERS,
) -> AnswerMetricScore:
    if case.expected_abstain:
        abstention_correct = 1.0 if looks_like_abstention(case.answer, abstain_markers=abstain_markers) else 0.0
        return AnswerMetricScore(
            case=case,
            fact_coverage=None,
            citation_grounding=None,
            source_locator_grounding=None,
            abstention_correct=abstention_correct,
            answer_success=abstention_correct == 1.0,
            failure_reason="" if abstention_correct == 1.0 else "abstention_mismatch",
        )

    fact_score, matched, missing = fact_coverage_details(
        case.answer,
        case.expected_facts,
        threshold=fact_match_threshold,
    )
    retrieval_context_coverage = id_coverage(case.context_evidence_ids, case.gold_evidence_ids)
    citation_gold_coverage = id_coverage(case.cited_evidence_ids, case.gold_evidence_ids)
    source_locator_score = locator_coverage(case.cited_source_locators, case.gold_source_locators)
    citation_required = bool(case.gold_evidence_ids)
    citation_passed = (
        not citation_required
        or citation_gold_coverage is not None
        and citation_gold_coverage >= success_citation_threshold
    )
    fact_passed = fact_score is None or fact_score >= success_fact_threshold
    abstained = looks_like_abstention(case.answer, abstain_markers=abstain_markers)
    substantive_answer = not abstained or fact_score is not None and fact_passed
    answer_success = fact_passed and citation_passed and substantive_answer
    failure_reason = _answer_failure_reason(
        case,
        fact_coverage=fact_score,
        retrieval_context_coverage=retrieval_context_coverage,
        citation_grounding=citation_gold_coverage,
        fact_passed=fact_passed,
        citation_passed=citation_passed,
        answer_success=answer_success,
        success_fact_threshold=success_fact_threshold,
        abstain_markers=abstain_markers,
    )
    return AnswerMetricScore(
        case=case,
        fact_coverage=fact_score,
        citation_grounding=citation_gold_coverage,
        source_locator_grounding=source_locator_score,
        abstention_correct=None,
        answer_success=answer_success,
        retrieval_context_coverage=retrieval_context_coverage,
        citation_gold_coverage=citation_gold_coverage,
        failure_reason=failure_reason,
        matched_facts=matched,
        missing_facts=missing,
    )


def fact_coverage(case: AnswerMetricCase) -> float:
    score, _, _ = fact_coverage_details(case.answer, case.expected_facts)
    return 1.0 if score is None else score


def fact_coverage_details(
    answer: str,
    expected_facts: Iterable[Any],
    *,
    threshold: float = 0.75,
) -> tuple[float | None, tuple[str, ...], tuple[str, ...]]:
    facts = _clean_tuple(expected_facts)
    if not facts:
        return None, (), ()
    matched: list[str] = []
    missing: list[str] = []
    for fact in facts:
        if _fact_matches(answer, fact, threshold=threshold):
            matched.append(fact)
        else:
            missing.append(fact)
    return len(matched) / len(facts), tuple(matched), tuple(missing)


def citation_grounding(case: AnswerMetricCase) -> float:
    if not case.cited_evidence_ids:
        return 0.0
    allowed = set(case.context_evidence_ids) | set(case.gold_evidence_ids)
    if not allowed:
        return 0.0
    grounded = sum(1 for citation in case.cited_evidence_ids if citation in allowed)
    return grounded / len(case.cited_evidence_ids)


def id_coverage(retrieved: Iterable[Any], required: Iterable[Any]) -> float | None:
    required_set = set(_clean_tuple(required))
    if not required_set:
        return None
    return len(required_set.intersection(_clean_tuple(retrieved))) / len(required_set)


def locator_coverage(retrieved: Iterable[Any], required: Iterable[Any]) -> float | None:
    required_locators = _clean_tuple(required)
    if not required_locators:
        return None
    retrieved_locators = _clean_tuple(retrieved)
    hits = 0
    for locator in required_locators:
        if any(_locator_matches(candidate, locator) for candidate in retrieved_locators):
            hits += 1
    return hits / len(required_locators)


def answer_relevance(case: AnswerMetricCase) -> float:
    question_terms = _token_set(case.question)
    if not question_terms:
        return 0.0
    answer_terms = _token_set(case.answer)
    return len(question_terms & answer_terms) / len(question_terms)


def faithfulness_proxy(case: AnswerMetricCase) -> float:
    if looks_like_abstention(case.answer):
        return 1.0 if case.expected_abstain else 0.0
    return fact_coverage(case) * citation_grounding(case)


def abstention_accuracy(case: AnswerMetricCase) -> float:
    abstained = looks_like_abstention(case.answer)
    return 1.0 if abstained == case.expected_abstain else 0.0


def evaluate_answer_case(case: AnswerMetricCase) -> tuple[MetricValue, ...]:
    return (
        MetricValue("fact_coverage", fact_coverage(case), {"case_id": case.case_id}),
        MetricValue("citation_grounding", citation_grounding(case), {"case_id": case.case_id}),
        MetricValue("answer_relevance", answer_relevance(case), {"case_id": case.case_id}),
        MetricValue("faithfulness_proxy", faithfulness_proxy(case), {"case_id": case.case_id}),
        MetricValue("abstention_accuracy", abstention_accuracy(case), {"case_id": case.case_id}),
    )


def looks_like_abstention(
    answer: str,
    *,
    abstain_markers: Sequence[str] = DEFAULT_ABSTAIN_MARKERS,
) -> bool:
    normalized = _normalize(answer)
    return any(_normalize(marker) in normalized for marker in abstain_markers if str(marker).strip())


def _answer_failure_reason(
    case: AnswerMetricCase,
    *,
    fact_coverage: float | None,
    retrieval_context_coverage: float | None,
    citation_grounding: float | None,
    fact_passed: bool,
    citation_passed: bool,
    answer_success: bool,
    success_fact_threshold: float,
    abstain_markers: Sequence[str],
) -> str:
    if answer_success:
        return ""
    if case.gold_evidence_ids:
        if case.retrieved_evidence_ids and id_coverage(case.retrieved_evidence_ids, case.gold_evidence_ids) != 1.0:
            return "missing_gold_in_retrieval"
        if retrieval_context_coverage is not None and retrieval_context_coverage < 1.0:
            return "missing_gold_in_llm_context"
        if citation_grounding is not None and citation_grounding < 1.0:
            return "missing_gold_citation"
    if not fact_passed and fact_coverage is not None and fact_coverage < success_fact_threshold:
        return "fact_match_low"
    if not citation_passed:
        return "missing_gold_citation"
    if looks_like_abstention(case.answer, abstain_markers=abstain_markers):
        return "unexpected_abstention"
    return "other"


def _fact_matches(answer: str, fact: str, *, threshold: float) -> bool:
    normalized_answer = _normalize(answer)
    normalized_fact = _normalize(fact)
    if not normalized_answer or not normalized_fact:
        return False
    if normalized_fact in normalized_answer:
        return True
    fact_tokens = _content_tokens(normalized_fact)
    if not fact_tokens:
        return False
    answer_tokens = set(_content_tokens(normalized_answer))
    overlap = sum(1 for token in fact_tokens if _token_matches(token, answer_tokens))
    return overlap / len(fact_tokens) >= _effective_fact_threshold(fact, fact_tokens, threshold)


def _effective_fact_threshold(fact: str, fact_tokens: tuple[str, ...], threshold: float) -> float:
    lowered = fact.casefold()
    effective = threshold
    if len(fact_tokens) >= 12:
        effective = min(effective, 0.55)
    if len(fact_tokens) >= 24:
        effective = min(effective, 0.45)
    if "nearby context" in lowered or "caption:" in lowered:
        effective = min(effective, 0.30)
    if "latex:" in lowered or "\\begin" in lowered or "[equation" in lowered:
        effective = min(effective, 0.35)
    return effective


def _locator_matches(candidate: str, required: str) -> bool:
    return bool(candidate and required) and (
        candidate == required
        or candidate.startswith(required)
        or required.startswith(candidate)
    )


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _token_set(text: str) -> set[str]:
    return {match.group(0).casefold() for match in re.finditer(r"[A-Za-z0-9_]+", str(text or ""))}


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(text.casefold()))


def _content_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _tokens(_strip_structural_fact_noise(text))
        if token not in _STRUCTURAL_FACT_STOPWORDS
        and not token.startswith("chunk_")
        and len(token) > 1
    )


def _strip_structural_fact_noise(text: str) -> str:
    text = re.sub(r"_\{([^}]+)\}", r"_\1", text)
    text = re.sub(r"\^\{([^}]+)\}", r"_\1", text)
    text = text.replace("\\", " ")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.split(r"\bSource\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return text


def _token_matches(token: str, answer_tokens: set[str]) -> bool:
    if token in answer_tokens:
        return True
    if len(token) > 3 and token.endswith("s") and token[:-1] in answer_tokens:
        return True
    if len(token) > 3 and f"{token}s" in answer_tokens:
        return True
    return False


def _clean_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return tuple(out)


__all__ = [
    "AnswerMetricCase",
    "AnswerMetricScore",
    "DEFAULT_ABSTAIN_MARKERS",
    "abstention_accuracy",
    "answer_relevance",
    "citation_grounding",
    "evaluate_answer_case",
    "fact_coverage",
    "fact_coverage_details",
    "faithfulness_proxy",
    "id_coverage",
    "locator_coverage",
    "looks_like_abstention",
    "score_answer_case",
]
