from __future__ import annotations

from backend.research.document.models import PaperChunk
from backend.research.rag.retrieval.contracts import (
    RetrievalRequest as ContractRetrievalRequest,
    RetrievalResult as ContractRetrievalResult,
)
from backend.research.rag.retrieval.paper_retriever import (
    RetrievalPolicy as CompatRetrievalPolicy,
    RetrievalRequest as CompatRetrievalRequest,
    RetrievalResult as CompatRetrievalResult,
)
from backend.research.rag.retrieval.policies import RetrievalPolicy as PolicyRetrievalPolicy


def _chunk(chunk_id: str, *, parent_chunk_id: str | None = None) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Results",
        section_role=["experiment"],
        section_index=3,
        parent_chunk_id=parent_chunk_id,
        content="The result paragraph reports better accuracy.",
        metadata={
            "source_ref": f"arxiv://p1/{chunk_id}",
            "claim_index_hit": True,
            "field_score": 0.7,
            "child_final_score": 0.8,
        },
    )


def test_paper_retriever_keeps_compatibility_contract_exports() -> None:
    assert CompatRetrievalPolicy is PolicyRetrievalPolicy
    assert CompatRetrievalRequest is ContractRetrievalRequest
    assert CompatRetrievalResult is ContractRetrievalResult


def test_retrieval_result_evidence_candidates_are_still_deduped_and_metadata_rich() -> None:
    child = _chunk("para-1", parent_chunk_id="sec-1")
    parent = _chunk("sec-1")
    result = ContractRetrievalResult(
        parent_chunks=[parent],
        child_chunks=[child, child],
        ref_chunks=[],
        intent="numerical_result",
    )

    evidence = result.as_evidence_candidates()

    assert [item["evidence_id"] for item in evidence] == ["para-1", "sec-1"]
    assert evidence[0]["source_ref"] == "arxiv://p1/para-1"
    assert evidence[0]["metadata"]["intent"] == "numerical_result"
    assert evidence[0]["metadata"]["claim_index_hit"] is True
    assert evidence[0]["metadata"]["field_score"] == 0.7
    assert evidence[0]["metadata"]["child_final_score"] == 0.8
