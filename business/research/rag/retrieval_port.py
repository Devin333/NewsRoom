from __future__ import annotations

from framework.harness.retrieval.evidence_pack import EvidencePack, EvidencePackCollection
from framework.harness.retrieval.ports import RetrievalPort
from framework.harness.retrieval.request import RetrievalRequest

from business.research.document.models import PaperChunk
from business.research.rag.retriever import ResearchRetriever, RetrievalRequest as ResearchRetrievalRequest


def _extract_paper_id(request: RetrievalRequest) -> str:
    """Extract paper_id from context_refs (arxiv://id/...) or fall back to scope."""
    for ref in request.context_refs:
        if ref.startswith("arxiv://"):
            part = ref.removeprefix("arxiv://").split("/")[0]
            if part:
                return part
    return request.scope


class PaperChunkRetrievalPort:
    """
    Adapter: framework RetrievalPort → ResearchRetriever.

    Convention:
      RetrievalRequest.scope     = paper_id
      RetrievalRequest.metadata  may include current_section_index (int)

    The reader's position is resolved with this precedence:
      1. request.metadata["current_section_index"]  (per-query override)
      2. default_section_index                       (per-session, from ReadingSession)
      3. 0                                           (reader hasn't picked a section)
    """

    def __init__(self, retriever: ResearchRetriever, *, default_section_index: int = 0) -> None:
        self._retriever = retriever
        self._default_section_index = max(0, default_section_index)

    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection:
        paper_id = _extract_paper_id(request)
        if not paper_id:
            return EvidencePackCollection(packs=(), metadata={"error": "no paper_id in scope"})

        section_index = self._resolve_section_index(request)
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
                "section_index": section_index,
            },
        )

    def _resolve_section_index(self, request: RetrievalRequest) -> int:
        raw = request.metadata.get("current_section_index")
        if raw is None:
            return self._default_section_index
        try:
            index = int(raw)
        except (TypeError, ValueError):
            return self._default_section_index
        return index if index >= 0 else self._default_section_index


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
