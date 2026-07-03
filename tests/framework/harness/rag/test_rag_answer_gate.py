from __future__ import annotations

from framework.harness.rag.answer_gate import RAGAnswerGate
from framework.harness.rag.models import AnswerClaim, EvidenceCandidate, GroundedAnswerCandidate, RAGContextPack


def test_rag_answer_gate_accepts_grounded_answer() -> None:
    candidate = _answer(cited=("ev-1",), claims=(AnswerClaim("c1", "The method retrieves evidence.", ("ev-1",)),))

    results = RAGAnswerGate().evaluate(candidate, _pack())

    assert all(result.passed for result in results)


def test_rag_answer_gate_rejects_pack_external_citation() -> None:
    candidate = _answer(cited=("missing",), claims=(AnswerClaim("c1", "Unsupported.", ("missing",)),))

    results = RAGAnswerGate().evaluate(candidate, _pack())

    failed = {result.gate_name: result for result in results if not result.passed}
    assert failed["rag_answer_citation_integrity"].details["missing_evidence_ids"] == ["missing"]


def test_rag_answer_gate_rejects_claim_without_evidence() -> None:
    candidate = _answer(cited=("ev-1",), claims=(AnswerClaim("c1", "Unsupported.", ()),))

    results = RAGAnswerGate().evaluate(candidate, _pack())

    failed = {result.gate_name: result for result in results if not result.passed}
    assert failed["rag_answer_claim_coverage"].details["unsupported_claims"][0]["claim_id"] == "c1"


def test_rag_answer_gate_allows_empty_verified_abstention() -> None:
    candidate = GroundedAnswerCandidate(
        answer_id="ans-1",
        question="Q?",
        answer_text="",
        cited_evidence_ids=(),
        claims=(),
        abstained=True,
    )

    results = RAGAnswerGate().evaluate(candidate, _pack())

    assert all(result.passed for result in results)


def test_rag_answer_gate_rejects_abstention_with_answer_text() -> None:
    candidate = GroundedAnswerCandidate(
        answer_id="ans-1",
        question="Q?",
        answer_text="I can answer after all.",
        cited_evidence_ids=(),
        claims=(),
        abstained=True,
    )

    results = RAGAnswerGate().evaluate(candidate, _pack())

    failed = {result.gate_name: result for result in results if not result.passed}
    assert failed["rag_answer_abstention_shape"].details["answer_chars"] > 0


def _answer(*, cited: tuple[str, ...], claims: tuple[AnswerClaim, ...]) -> GroundedAnswerCandidate:
    return GroundedAnswerCandidate(
        answer_id="ans-1",
        question="Q?",
        answer_text="The method retrieves evidence. [ev-1]",
        cited_evidence_ids=cited,
        claims=claims,
    )


def _pack() -> RAGContextPack:
    evidence = EvidenceCandidate(
        evidence_id="ev-1",
        title="Method",
        summary="The method retrieves evidence.",
        source_ref="source://paper#method",
        span_refs=("source://paper#method:p1",),
        evidence_type="method",
        confidence=0.9,
        lineage=("retrieval.fake",),
    )
    return RAGContextPack(
        pack_id="pack-1",
        query="Q?",
        accepted_evidence=(evidence,),
    )
