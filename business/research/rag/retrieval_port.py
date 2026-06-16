from __future__ import annotations

from framework.harness.retrieval.evidence_pack import EvidencePack, EvidencePackCollection
from framework.harness.retrieval.ports import RetrievalPort
from framework.harness.retrieval.request import RetrievalRequest

from business.research.document.models import PaperChunk
from business.research.rag.retriever import ResearchRetriever, RetrievalRequest as ResearchRetrievalRequest


class PaperChunkRetrievalPort:
    """
    Adapter: framework RetrievalPort → ResearchRetriever.

    Convention:
      RetrievalRequest.scope     = paper_id
      RetrievalRequest.metadata  may include current_section_index (int)
    """

    def __init__(self, retriever: ResearchRetriever) -> None:
        self._retriever = retriever

    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection:
        paper_id = request.scope or (request.context_refs[0] if request.context_refs else "")
        if not paper_id:
            return EvidencePackCollection(packs=(), metadata={"error": "no paper_id in scope"})

        section_index = int(request.metadata.get("current_section_index", 0))
        result = self._retriever.retrieve(ResearchRetrievalRequest(
            paper_id=paper_id,
            question=request.query,
            current_section_index=section_index,
            limit=request.limit,
        ))

        packs = tuple(
            _chunk_to_evidence_pack(chunk)
            for chunk in result.parent_chunks
        )
        return EvidencePackCollection(
            packs=packs,
            metadata={
                "intent": result.intent,
                "child_count": len(result.child_chunks),
                "ref_count": len(result.ref_chunks),
            },
        )


def _chunk_to_evidence_pack(chunk: PaperChunk) -> EvidencePack:
    source_ref = chunk.metadata.get("source_ref") or f"arxiv://{chunk.paper_id}/{chunk.chunk_id}"
    return EvidencePack(
        evidence_id=chunk.chunk_id,
        title=chunk.section_title or chunk.chunk_type,
        summary=chunk.content[:1200],
        source_refs=(source_ref,),
        confidence=0.8,
        freshness="current",
        lineage=(chunk.paper_id,),
        metadata={
            "section_role": chunk.section_role,
            "section_index": chunk.section_index,
            "chunk_type": chunk.chunk_type,
            "has_formula": chunk.has_formula,
            "has_figure": chunk.has_figure,
        },
    )


# Verify structural compliance at import time
assert isinstance(PaperChunkRetrievalPort(None), RetrievalPort)  # type: ignore[arg-type]

__all__ = ["PaperChunkRetrievalPort"]
