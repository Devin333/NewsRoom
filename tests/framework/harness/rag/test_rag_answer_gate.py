from __future__ import annotations

from framework.harness.rag.answer_gate import RAGAnswerGate
from framework.harness.rag.models import AnswerClaim, EvidenceCandidate, GroundedAnswerCandidate, RAGContextPack
from framework.harness.retrieval.evidence_pack import EvidencePack


def test_rag_answer_gate_accepts_grounded_answer() -> None:
    candidate = _answer(
        cited=("ev-1",),
        claims=(
            AnswerClaim(
                "c1",
                "The method retrieves evidence.",
                ("ev-1",),
                span_refs=("source://paper#method:p1",),
            ),
        ),
    )

    results = RAGAnswerGate().evaluate(candidate, _pack())

    assert all(result.passed for result in results)
    assert candidate.claims[0].to_dict()["span_refs"] == ["source://paper#method:p1"]


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


def test_rag_answer_gate_rejects_claim_without_span_refs() -> None:
    candidate = _answer(cited=("ev-1",), claims=(AnswerClaim("c1", "Unsupported.", ("ev-1",)),))

    results = RAGAnswerGate().evaluate(candidate, _pack())

    failed = {result.gate_name: result for result in results if not result.passed}
    details = failed["rag_answer_span_citation_integrity"].details
    assert details["missing_claim_span_refs"] == [{"claim_id": "c1", "evidence_ids": ["ev-1"]}]


def test_rag_answer_gate_rejects_unknown_claim_span_refs() -> None:
    candidate = _answer(
        cited=("ev-1",),
        claims=(AnswerClaim("c1", "Unsupported.", ("ev-1",), span_refs=("source://paper#unknown",)),),
    )

    results = RAGAnswerGate().evaluate(candidate, _pack())

    failed = {result.gate_name: result for result in results if not result.passed}
    details = failed["rag_answer_span_citation_integrity"].details
    assert details["unknown_claim_span_refs"] == [{"claim_id": "c1", "span_ref": "source://paper#unknown"}]
    assert details["evidence_ids_without_claim_span_refs"] == [{"claim_id": "c1", "evidence_ids": ["ev-1"]}]


def test_rag_answer_gate_rejects_span_from_uncited_evidence() -> None:
    candidate = _answer(
        cited=("ev-1",),
        claims=(AnswerClaim("c1", "Unsupported.", ("ev-1",), span_refs=("source://paper#results:p1",)),),
    )

    results = RAGAnswerGate().evaluate(candidate, _pack(extra_evidence=(_evidence("ev-2", "Results", "source://paper#results:p1"),)))

    failed = {result.gate_name: result for result in results if not result.passed}
    details = failed["rag_answer_span_citation_integrity"].details
    assert details["mismatched_claim_span_refs"] == [
        {
            "claim_id": "c1",
            "span_ref": "source://paper#results:p1",
            "owner_evidence_ids": ["ev-2"],
            "claim_evidence_ids": ["ev-1"],
        }
    ]


def test_rag_answer_gate_uses_evidence_pack_source_refs_as_span_fallback() -> None:
    candidate = _answer(
        cited=("pack-ev-1",),
        claims=(AnswerClaim("c1", "Fallback span.", ("pack-ev-1",), span_refs=("source://pack#span",)),),
    )
    pack = RAGContextPack(
        pack_id="pack-1",
        query="Q?",
        evidence=(
            EvidencePack(
                evidence_id="pack-ev-1",
                title="Fallback",
                summary="Fallback span.",
                source_refs=("source://pack#span",),
                confidence=0.9,
                freshness="static",
                lineage=("retrieval.fake",),
            ),
        ),
    )

    results = RAGAnswerGate().evaluate(candidate, pack)

    assert all(result.passed for result in results)


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


def _pack(*, extra_evidence: tuple[EvidenceCandidate, ...] = ()) -> RAGContextPack:
    evidence = _evidence("ev-1", "Method", "source://paper#method:p1")
    return RAGContextPack(
        pack_id="pack-1",
        query="Q?",
        accepted_evidence=(evidence, *extra_evidence),
    )


def _evidence(evidence_id: str, title: str, span_ref: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        title=title,
        summary="The method retrieves evidence.",
        source_ref="source://paper#method",
        span_refs=(span_ref,),
        evidence_type="method",
        confidence=0.9,
        lineage=("retrieval.fake",),
    )
