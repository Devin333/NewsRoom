from __future__ import annotations

from business.research.document.models import PaperChunk
from business.research.rag.adapters.answer_worker import PaperAnswerWorker
from business.research.rag.retrieval.paper_answer_generator import AnswerGenerator
from framework.harness.rag.models import EvidenceCandidate, RAGContextPack


def test_paper_answer_worker_maps_generated_chunk_ids_to_evidence_ids() -> None:
    async def fake_llm(prompt: str) -> str:
        assert "Method evidence" in prompt
        return "The paper uses a retrieval method supported by context [1]."

    worker = PaperAnswerWorker(AnswerGenerator(fake_llm, max_context_chunks=1))
    pack = RAGContextPack(
        pack_id="pack-1",
        query="What method does the paper use?",
        accepted_evidence=(
            _evidence(
                "ev-method",
                _chunk(
                    "chunk-method",
                    "Method evidence: the system retrieves and verifies paper evidence.",
                    chunk_type="paragraph",
                ),
            ),
        ),
    )

    candidate = worker.generate_answer(question="What method does the paper use?", pack=pack)

    assert candidate.abstained is False
    assert candidate.answer_text == "The paper uses a retrieval method supported by context [1]."
    assert candidate.cited_evidence_ids == ("ev-method",)
    assert candidate.claims[0].evidence_ids == ("ev-method",)
    assert candidate.claims[0].span_refs == ("chunk-method",)
    assert candidate.metadata["context_chunk_ids"] == ["chunk-method"]
    assert candidate.metadata["chunk_to_evidence_id"] == {"chunk-method": "ev-method"}
    assert candidate.metadata["evidence_id_to_span_refs"] == {"ev-method": ["chunk-method"]}
    assert candidate.metadata["claims_degraded"] is True


def test_paper_answer_worker_can_rebuild_chunk_from_flat_evidence_metadata() -> None:
    async def fake_llm(prompt: str) -> str:
        assert "Table evidence" in prompt
        return "The table shows stronger results for the proposed model [1]."

    worker = PaperAnswerWorker(AnswerGenerator(fake_llm, max_context_chunks=1))
    evidence = EvidenceCandidate(
        evidence_id="ev-table",
        title="Table",
        summary="Table evidence: proposed model improves accuracy.",
        source_ref="paper://p1/pdf#page=4",
        span_refs=("chunk-table",),
        evidence_type="experiment",
        confidence=0.9,
        lineage=("retrieval.test",),
        metadata={
            "rag_chunk_id": "chunk-table",
            "paper_id": "p1",
            "parse_source": "pymupdf",
            "chunk_type": "table",
            "has_table": True,
            "section_title": "Experiments",
            "section_role": ["experiment"],
            "content": "Table evidence: proposed model improves accuracy.",
        },
    )
    pack = RAGContextPack(pack_id="pack-1", query="What do results show?", accepted_evidence=(evidence,))

    candidate = worker.generate_answer(question="What do results show?", pack=pack)

    assert candidate.abstained is False
    assert candidate.cited_evidence_ids == ("ev-table",)
    assert candidate.claims[0].span_refs == ("chunk-table",)
    assert candidate.metadata["context_chunk_ids"] == ["chunk-table"]


def test_paper_answer_worker_abstains_when_context_lacks_paper_chunk_metadata() -> None:
    async def fake_llm(prompt: str) -> str:
        raise AssertionError("LLM should not be called without paper context")

    worker = PaperAnswerWorker(AnswerGenerator(fake_llm))
    pack = RAGContextPack(
        pack_id="pack-missing",
        query="What method does the paper use?",
        accepted_evidence=(
            EvidenceCandidate(
                evidence_id="ev-1",
                title="Unstructured evidence",
                summary="A short summary without paper ids.",
                source_ref="source://x",
                span_refs=("span-1",),
                evidence_type="method",
                confidence=0.9,
                lineage=("retrieval.test",),
            ),
        ),
    )

    candidate = worker.generate_answer(question="What method does the paper use?", pack=pack)

    assert candidate.abstained is True
    assert candidate.answer_text == ""
    assert candidate.cited_evidence_ids == ()
    assert candidate.metadata["abstention_reason"] == "context pack lacks paper_chunk metadata"


def test_paper_answer_worker_normalizes_context_absence_answer_to_abstention() -> None:
    async def fake_llm(prompt: str) -> str:
        assert "Method evidence" in prompt
        return (
            "No. The provided context describes retrieval and verification, "
            "but it does not provide operating instructions for a microwave oven [1]."
        )

    worker = PaperAnswerWorker(AnswerGenerator(fake_llm, max_context_chunks=1))
    pack = RAGContextPack(
        pack_id="pack-1",
        query="Does this paper provide operating instructions for a microwave oven?",
        accepted_evidence=(
            _evidence(
                "ev-method",
                _chunk(
                    "chunk-method",
                    "Method evidence: the system retrieves and verifies paper evidence.",
                    chunk_type="paragraph",
                ),
            ),
        ),
    )

    candidate = worker.generate_answer(
        question="Does this paper provide operating instructions for a microwave oven?",
        pack=pack,
    )

    assert candidate.abstained is True
    assert candidate.answer_text == ""
    assert candidate.cited_evidence_ids == ()
    assert candidate.claims == ()
    assert candidate.metadata["abstention_reason"] == "answer generator reported insufficient context"
    assert "microwave oven" in candidate.metadata["generated_answer"]["answer"]


def _chunk(chunk_id: str, content: str, *, chunk_type: str = "paragraph") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="pymupdf",
        chunk_type=chunk_type,
        section_title="Method",
        section_role=["method"],
        content=content,
        metadata={"source_locator": "paper://p1/pdf#page=1"},
    )


def _evidence(evidence_id: str, chunk: PaperChunk) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        title=chunk.section_title,
        summary=chunk.content,
        source_ref="paper://p1/pdf#page=1",
        span_refs=(chunk.chunk_id,),
        evidence_type="method",
        confidence=0.9,
        lineage=("retrieval.test",),
        metadata={"paper_chunk": chunk.model_dump(mode="json")},
    )
