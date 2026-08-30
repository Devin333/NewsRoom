from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.research.rag.retrieval.paper_answer_generator import GeneratedAnswer

logger = logging.getLogger(__name__)

LLMCall = Callable[[str], Awaitable[str]]
_SUPPORTED = "supported"
_CONTRADICTED = "contradicted"
_INSUFFICIENT = "insufficient"
_CLAIM_VERDICTS = frozenset({_SUPPORTED, _CONTRADICTED, _INSUFFICIENT})


@dataclass(frozen=True)
class GenerationClaimJudgment:
    claim_text: str
    verdict: str
    support_chunk_ids: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_text": self.claim_text,
            "verdict": self.verdict,
            "support_chunk_ids": list(self.support_chunk_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CitationGroundingJudgment:
    claim_text: str
    cited_chunk_ids: tuple[str, ...] = ()
    support_chunk_ids: tuple[str, ...] = ()
    citation_supports_claim: bool = False
    wrong_citation: bool = False
    missing_citation: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_text": self.claim_text,
            "cited_chunk_ids": list(self.cited_chunk_ids),
            "support_chunk_ids": list(self.support_chunk_ids),
            "citation_supports_claim": self.citation_supports_claim,
            "wrong_citation": self.wrong_citation,
            "missing_citation": self.missing_citation,
            "reason": self.reason,
        }


@dataclass
class GenerationScores:
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    claim_support_rate: float | None = None
    contradiction_rate: float | None = None
    unsupported_claim_rate: float | None = None
    citation_grounding_rate: float | None = None
    citation_claim_support_rate: float | None = None
    wrong_citation_rate: float | None = None
    missing_citation_rate: float | None = None
    grounded_answer_rate: float | None = None
    judge_error: bool = False

    def to_dict(self) -> dict:
        return {
            "faithfulness": round(self.faithfulness, 3),
            "answer_relevancy": round(self.answer_relevancy, 3),
            "context_precision": round(self.context_precision, 3),
            "claim_support_rate": round(_score_or(self.claim_support_rate, self.faithfulness), 3),
            "contradiction_rate": round(_score_or(self.contradiction_rate, 0.0), 3),
            "unsupported_claim_rate": round(_score_or(self.unsupported_claim_rate, 1.0 - self.faithfulness), 3),
            "citation_grounding_rate": round(_score_or(self.citation_grounding_rate, self.context_precision), 3),
            "citation_claim_support_rate": round(
                _score_or(self.citation_claim_support_rate, self.context_precision),
                3,
            ),
            "wrong_citation_rate": round(_score_or(self.wrong_citation_rate, 0.0), 3),
            "missing_citation_rate": round(_score_or(self.missing_citation_rate, 0.0), 3),
            "grounded_answer_rate": round(_score_or(self.grounded_answer_rate, self.faithfulness), 3),
            "judge_error": self.judge_error,
        }


@dataclass
class GenerationSampleJudgment:
    question: str
    answer: str
    context_chunk_ids: tuple[str, ...] = ()
    claims: tuple[GenerationClaimJudgment, ...] = ()
    citation_checks: tuple[CitationGroundingJudgment, ...] = ()
    scores: GenerationScores = field(default_factory=lambda: GenerationScores(0.0, 0.0, 0.0, judge_error=True))
    status: str = "pass"
    reason: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "context_chunk_ids": list(self.context_chunk_ids),
            "status": self.status,
            "reason": self.reason,
            "claims": [claim.to_dict() for claim in self.claims],
            "citation_checks": [check.to_dict() for check in self.citation_checks],
            "scores": self.scores.to_dict(),
            "raw_response": dict(self.raw_response),
        }


@dataclass
class GenerationEvalResult:
    per_sample: list[GenerationScores] = field(default_factory=list)
    sample_judgments: list[GenerationSampleJudgment] = field(default_factory=list)

    def _avg(self, attr: str) -> float:
        vals = [_score_or(getattr(score, attr), 0.0) for score in self.per_sample]
        return sum(vals) / len(vals) if vals else 0.0

    def faithfulness_score(self) -> float:
        return self._avg("faithfulness")

    def answer_relevancy_score(self) -> float:
        return self._avg("answer_relevancy")

    def context_precision_score(self) -> float:
        return self._avg("context_precision")

    def claim_support_rate_score(self) -> float:
        return self._avg("claim_support_rate")

    def contradiction_rate_score(self) -> float:
        return self._avg("contradiction_rate")

    def unsupported_claim_rate_score(self) -> float:
        return self._avg("unsupported_claim_rate")

    def citation_grounding_rate_score(self) -> float:
        return self._avg("citation_grounding_rate")

    def citation_claim_support_rate_score(self) -> float:
        return self._avg("citation_claim_support_rate")

    def wrong_citation_rate_score(self) -> float:
        return self._avg("wrong_citation_rate")

    def missing_citation_rate_score(self) -> float:
        return self._avg("missing_citation_rate")

    def grounded_answer_rate_score(self) -> float:
        return self._avg("grounded_answer_rate")

    def judge_error_rate(self) -> float:
        return sum(1 for score in self.per_sample if score.judge_error) / len(self.per_sample) if self.per_sample else 0.0

    def report(self) -> str:
        n = len(self.per_sample)
        return (
            f"=== 生成测评 (n={n}) ===\n"
            f"  Faithfulness      = {self.faithfulness_score():.3f}\n"
            f"  Answer Relevancy  = {self.answer_relevancy_score():.3f}\n"
            f"  Context Precision = {self.context_precision_score():.3f}\n"
            f"  Claim Support     = {self.claim_support_rate_score():.3f}\n"
            f"  Unsupported Claim = {self.unsupported_claim_rate_score():.3f}\n"
            f"  Citation Support  = {self.citation_claim_support_rate_score():.3f}\n"
            f"  Wrong Citation    = {self.wrong_citation_rate_score():.3f}\n"
            f"  Missing Citation  = {self.missing_citation_rate_score():.3f}\n"
            f"  Judge Error Rate  = {self.judge_error_rate():.3f}"
        )


def _extract_float(text: str, default: float = 0.0) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return default
    val = float(m.group(1))
    return max(0.0, min(1.0, val / 100.0 if val > 1.0 else val))


def _parse_yes_ratio(text: str) -> float:
    tokens = re.findall(r"\b(yes|no)\b", text.lower())
    if not tokens:
        return 0.0
    return sum(1 for token in tokens if token == "yes") / len(tokens)


class GenerationEvaluator:
    """LLM-as-judge generation eval with claim-level grounding diagnostics."""

    def __init__(self, judge_llm: LLMCall, *, max_concurrency: int = 3) -> None:
        self._llm = judge_llm
        self._sem = asyncio.Semaphore(max_concurrency)

    async def evaluate(self, answers: list[GeneratedAnswer]) -> GenerationEvalResult:
        judgments = await asyncio.gather(*[self._score_one(answer) for answer in answers])
        return GenerationEvalResult(
            per_sample=[judgment.scores for judgment in judgments],
            sample_judgments=list(judgments),
        )

    async def _score_one(self, ans: GeneratedAnswer) -> GenerationSampleJudgment:
        async with self._sem:
            return await self._structured_answer_judge(ans)

    async def _structured_answer_judge(self, ans: GeneratedAnswer) -> GenerationSampleJudgment:
        try:
            payload = _extract_json_object(await self._llm(_structured_judge_prompt(ans)))
            claims = _claims_from_payload(payload, ans)
            citation_checks = _citation_checks_from_payload(payload, ans, claims)
            scores = _scores_from_judgment(payload, claims, citation_checks)
            return GenerationSampleJudgment(
                question=ans.question,
                answer=ans.answer,
                context_chunk_ids=tuple(ans.context_chunk_ids),
                claims=tuple(claims),
                citation_checks=tuple(citation_checks),
                scores=scores,
                status=_sample_status(scores),
                reason=str(payload.get("reason") or "").strip()[:500],
                raw_response=payload,
            )
        except Exception as exc:  # noqa: BLE001 - benchmark judge errors are reported per sample
            logger.warning("structured generation judge failed: %s", exc)
            score = GenerationScores(
                faithfulness=0.0,
                answer_relevancy=0.0,
                context_precision=0.0,
                claim_support_rate=0.0,
                contradiction_rate=0.0,
                unsupported_claim_rate=1.0 if ans.answer.strip() else 0.0,
                citation_grounding_rate=0.0,
                citation_claim_support_rate=0.0,
                wrong_citation_rate=0.0,
                missing_citation_rate=0.0,
                grounded_answer_rate=0.0,
                judge_error=True,
            )
            return GenerationSampleJudgment(
                question=ans.question,
                answer=ans.answer,
                context_chunk_ids=tuple(ans.context_chunk_ids),
                scores=score,
                status="error",
                reason=type(exc).__name__,
            )

    async def _faithfulness(self, ans: GeneratedAnswer) -> float:
        context = "\n\n".join(ans.contexts)
        prompt = (
            "Break the ANSWER into individual factual claims. For each claim, judge whether "
            "it can be inferred from the CONTEXT. Reply one line per claim as 'yes' or 'no'.\n\n"
            f"CONTEXT:\n{context[:4000]}\n\n"
            f"ANSWER:\n{ans.answer}\n\n"
            "Verdicts (yes/no per claim):"
        )
        try:
            return _parse_yes_ratio(await self._llm(prompt))
        except Exception as exc:
            logger.warning("faithfulness judge failed: %s", exc)
            return 0.0

    async def _answer_relevancy(self, ans: GeneratedAnswer) -> float:
        prompt = (
            "On a scale of 0 to 100, how directly and completely does the ANSWER address the "
            "QUESTION? Reply with only the number.\n\n"
            f"QUESTION: {ans.question}\n\n"
            f"ANSWER: {ans.answer}\n\n"
            "Score (0-100):"
        )
        try:
            return _extract_float(await self._llm(prompt))
        except Exception as exc:
            logger.warning("relevancy judge failed: %s", exc)
            return 0.0

    async def _context_precision(self, ans: GeneratedAnswer) -> float:
        if not ans.contexts:
            return 0.0
        prompt = (
            "For each numbered passage, judge whether it is relevant for answering the QUESTION. "
            "Reply one line per passage as 'yes' or 'no'.\n\n"
            f"QUESTION: {ans.question}\n\n"
            + "\n\n".join(f"[{index + 1}] {context[:600]}" for index, context in enumerate(ans.contexts))
            + "\n\nVerdicts (yes/no per passage):"
        )
        try:
            return _parse_yes_ratio(await self._llm(prompt))
        except Exception as exc:
            logger.warning("context precision judge failed: %s", exc)
            return 0.0


def _structured_judge_prompt(ans: GeneratedAnswer) -> str:
    contexts = [
        {"index": index + 1, "chunk_id": chunk_id, "text": context[:1000]}
        for index, (chunk_id, context) in enumerate(zip(ans.context_chunk_ids, ans.contexts, strict=False))
    ]
    return "\n".join([
        "You are evaluating a retrieval-augmented answer for a scientific paper QA benchmark.",
        "Return JSON only. Do not include markdown.",
        "Break the ANSWER into atomic factual claims and judge each claim using only the CONTEXT.",
        "Also judge whether the answer citations point to passages that support the cited claim.",
        "Use only these claim verdicts: supported, contradicted, insufficient.",
        "JSON schema:",
        json.dumps({
            "claims": [
                {
                    "claim_text": "one atomic factual claim",
                    "verdict": "supported",
                    "support_chunk_ids": ["chunk-id"],
                    "reason": "short reason",
                }
            ],
            "citation_checks": [
                {
                    "claim_text": "claim being checked",
                    "cited_chunk_ids": ["chunk-id cited by the answer"],
                    "support_chunk_ids": ["chunk-id that actually supports the claim"],
                    "citation_supports_claim": True,
                    "wrong_citation": False,
                    "missing_citation": False,
                    "reason": "short reason",
                }
            ],
            "answer_relevance": 1.0,
            "context_precision": 1.0,
            "reason": "overall short reason",
        }, ensure_ascii=False),
        "",
        f"QUESTION: {ans.question}",
        f"ANSWER: {ans.answer}",
        "CONTEXT:",
        json.dumps(contexts, ensure_ascii=False),
    ])


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("generation judge response must be a JSON object")
    return payload


def _claims_from_payload(payload: dict[str, Any], ans: GeneratedAnswer) -> list[GenerationClaimJudgment]:
    raw_claims = payload.get("claims")
    claims: list[GenerationClaimJudgment] = []
    if isinstance(raw_claims, list):
        for raw in raw_claims:
            if not isinstance(raw, dict):
                continue
            claim_text = str(raw.get("claim_text") or raw.get("claim") or "").strip()
            if not claim_text:
                continue
            claims.append(GenerationClaimJudgment(
                claim_text=claim_text,
                verdict=_normalized_verdict(raw.get("verdict")),
                support_chunk_ids=tuple(_known_chunk_ids(raw.get("support_chunk_ids"), ans.context_chunk_ids)),
                reason=str(raw.get("reason") or "").strip()[:500],
            ))
    if claims:
        return claims
    return [
        GenerationClaimJudgment(
            claim_text=sentence,
            verdict=_SUPPORTED,
            support_chunk_ids=tuple(_cited_chunk_ids(sentence, ans.context_chunk_ids)),
            reason="fallback_sentence_split",
        )
        for sentence in _answer_sentences(ans.answer)
    ]


def _citation_checks_from_payload(
    payload: dict[str, Any],
    ans: GeneratedAnswer,
    claims: list[GenerationClaimJudgment],
) -> list[CitationGroundingJudgment]:
    raw_checks = payload.get("citation_checks")
    checks: list[CitationGroundingJudgment] = []
    if isinstance(raw_checks, list):
        for raw in raw_checks:
            if not isinstance(raw, dict):
                continue
            claim_text = str(raw.get("claim_text") or raw.get("claim") or "").strip()
            if not claim_text:
                continue
            cited = tuple(_known_chunk_ids(raw.get("cited_chunk_ids"), ans.context_chunk_ids))
            support = tuple(_known_chunk_ids(raw.get("support_chunk_ids"), ans.context_chunk_ids))
            missing = bool(raw.get("missing_citation"))
            wrong = bool(raw.get("wrong_citation"))
            supports = bool(raw.get("citation_supports_claim")) and not wrong and not missing
            checks.append(CitationGroundingJudgment(
                claim_text=claim_text,
                cited_chunk_ids=cited,
                support_chunk_ids=support,
                citation_supports_claim=supports,
                wrong_citation=wrong,
                missing_citation=missing,
                reason=str(raw.get("reason") or "").strip()[:500],
            ))
    return checks or [_deterministic_citation_check(ans, claim) for claim in claims]


def _deterministic_citation_check(ans: GeneratedAnswer, claim: GenerationClaimJudgment) -> CitationGroundingJudgment:
    cited = tuple(_cited_chunk_ids(claim.claim_text, ans.context_chunk_ids))
    support = claim.support_chunk_ids
    missing = claim.verdict == _SUPPORTED and bool(support) and not cited
    wrong = bool(cited) and bool(support) and not set(cited).intersection(support)
    supports = bool(cited) and not wrong and not missing and (
        not support or bool(set(cited).intersection(support))
    )
    return CitationGroundingJudgment(
        claim_text=claim.claim_text,
        cited_chunk_ids=cited,
        support_chunk_ids=support,
        citation_supports_claim=supports,
        wrong_citation=wrong,
        missing_citation=missing,
        reason="deterministic citation check",
    )


def _scores_from_judgment(
    payload: dict[str, Any],
    claims: list[GenerationClaimJudgment],
    citation_checks: list[CitationGroundingJudgment],
) -> GenerationScores:
    claim_count = len(claims)
    supported = sum(1 for claim in claims if claim.verdict == _SUPPORTED)
    contradicted = sum(1 for claim in claims if claim.verdict == _CONTRADICTED)
    insufficient = sum(1 for claim in claims if claim.verdict == _INSUFFICIENT)
    claim_support_rate = supported / claim_count if claim_count else 0.0
    contradiction_rate = contradicted / claim_count if claim_count else 0.0
    unsupported_claim_rate = (contradicted + insufficient) / claim_count if claim_count else 0.0
    check_count = len(citation_checks)
    citation_support = sum(1 for check in citation_checks if check.citation_supports_claim)
    wrong_citation = sum(1 for check in citation_checks if check.wrong_citation)
    missing_citation = sum(1 for check in citation_checks if check.missing_citation)
    citation_claim_support_rate = citation_support / check_count if check_count else 1.0
    wrong_citation_rate = wrong_citation / check_count if check_count else 0.0
    missing_citation_rate = missing_citation / check_count if check_count else 0.0
    citation_grounding_rate = citation_claim_support_rate
    answer_relevance = _clamped_float(payload.get("answer_relevance"), default=claim_support_rate)
    context_precision = _clamped_float(payload.get("context_precision"), default=citation_grounding_rate)
    grounded_answer_rate = min(claim_support_rate, citation_grounding_rate)
    return GenerationScores(
        faithfulness=claim_support_rate,
        answer_relevancy=answer_relevance,
        context_precision=context_precision,
        claim_support_rate=claim_support_rate,
        contradiction_rate=contradiction_rate,
        unsupported_claim_rate=unsupported_claim_rate,
        citation_grounding_rate=citation_grounding_rate,
        citation_claim_support_rate=citation_claim_support_rate,
        wrong_citation_rate=wrong_citation_rate,
        missing_citation_rate=missing_citation_rate,
        grounded_answer_rate=grounded_answer_rate,
    )


def _sample_status(scores: GenerationScores) -> str:
    if scores.judge_error:
        return "error"
    if _score_or(scores.contradiction_rate, 0.0) > 0.0:
        return "fail"
    if _score_or(scores.claim_support_rate, 0.0) < 0.85:
        return "fail"
    if _score_or(scores.wrong_citation_rate, 0.0) > 0.0 or _score_or(scores.missing_citation_rate, 0.0) > 0.0:
        return "warning"
    return "pass"


def _normalized_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    return verdict if verdict in _CLAIM_VERDICTS else _INSUFFICIENT


def _known_chunk_ids(value: Any, context_chunk_ids: list[str]) -> list[str]:
    values = value if isinstance(value, list) else [value]
    known = set(context_chunk_ids)
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        chunk_id = _chunk_id_from_reference(text, context_chunk_ids)
        if chunk_id not in known or chunk_id in seen:
            continue
        out.append(chunk_id)
        seen.add(chunk_id)
    return out


def _chunk_id_from_reference(value: str, context_chunk_ids: list[str]) -> str:
    normalized = value.strip()
    if normalized in set(context_chunk_ids):
        return normalized
    match = re.fullmatch(r"(?:context|passage|source)?\s*\[?(\d+)\]?", normalized, flags=re.IGNORECASE)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(context_chunk_ids):
            return context_chunk_ids[index]
    return normalized


def _cited_chunk_ids(text: str, context_chunk_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\[(\d+)\]", text):
        index = int(match.group(1)) - 1
        if index < 0 or index >= len(context_chunk_ids):
            continue
        chunk_id = context_chunk_ids[index]
        if chunk_id in seen:
            continue
        out.append(chunk_id)
        seen.add(chunk_id)
    return out


def _answer_sentences(answer: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？])\s+", str(answer or ""))
        if sentence.strip()
    ]


def _clamped_float(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _score_or(value: float | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "CitationGroundingJudgment",
    "GenerationClaimJudgment",
    "GenerationEvaluator",
    "GenerationEvalResult",
    "GenerationSampleJudgment",
    "GenerationScores",
]
