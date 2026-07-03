from __future__ import annotations

from typing import Any

from framework.harness.rag.gates import RAGGateResult
from framework.harness.rag.models import GroundedAnswerCandidate, RAGContextPack


class RAGAnswerGate:
    """Pure deterministic verification for grounded answer candidates."""

    def evaluate(
        self,
        candidate: GroundedAnswerCandidate,
        pack: RAGContextPack,
    ) -> tuple[RAGGateResult, ...]:
        available = {item.evidence_id for item in pack.accepted_evidence}
        if not available:
            available = {item.evidence_id for item in pack.evidence}
        return (
            _citation_integrity(candidate, available),
            _claim_coverage(candidate),
            _answer_shape(candidate),
            _abstention_shape(candidate),
        )


def _citation_integrity(candidate: GroundedAnswerCandidate, available: set[str]) -> RAGGateResult:
    cited = set(candidate.cited_evidence_ids)
    claim_cited = {evidence_id for claim in candidate.claims for evidence_id in claim.evidence_ids}
    missing = sorted((cited | claim_cited) - available)
    return RAGGateResult(
        "rag_answer_citation_integrity",
        not missing,
        None if not missing else "answer cites evidence ids outside the verified context pack",
        {
            "available_evidence_ids": sorted(available),
            "cited_evidence_ids": sorted(cited),
            "claim_evidence_ids": sorted(claim_cited),
            "missing_evidence_ids": missing,
        },
    )


def _claim_coverage(candidate: GroundedAnswerCandidate) -> RAGGateResult:
    uncovered = [
        {"claim_id": claim.claim_id, "text": claim.text}
        for claim in candidate.claims
        if not claim.evidence_ids
    ]
    return RAGGateResult(
        "rag_answer_claim_coverage",
        candidate.abstained or not uncovered,
        None if candidate.abstained or not uncovered else "one or more answer claims lack evidence ids",
        {"unsupported_claims": uncovered, "claim_count": len(candidate.claims)},
    )


def _answer_shape(candidate: GroundedAnswerCandidate) -> RAGGateResult:
    nonempty = bool(candidate.answer_text.strip())
    passed = candidate.abstained or nonempty
    return RAGGateResult(
        "rag_answer_shape",
        passed,
        None if passed else "non-abstention answer text is empty",
        {"answer_chars": len(candidate.answer_text.strip()), "abstained": candidate.abstained},
    )


def _abstention_shape(candidate: GroundedAnswerCandidate) -> RAGGateResult:
    text = candidate.answer_text.strip()
    passed = not candidate.abstained or not text
    return RAGGateResult(
        "rag_answer_abstention_shape",
        passed,
        None if passed else "abstention candidates must not include answer text",
        {"abstained": candidate.abstained, "answer_chars": len(text)},
    )


def unsupported_claims_from_answer_gate(results: tuple[RAGGateResult, ...]) -> tuple[dict[str, Any], ...]:
    claims: list[dict[str, Any]] = []
    for result in results:
        if result.passed:
            continue
        claims.extend(dict(item) for item in result.details.get("unsupported_claims", ()))
    return tuple(claims)


__all__ = ["RAGAnswerGate", "unsupported_claims_from_answer_gate"]
