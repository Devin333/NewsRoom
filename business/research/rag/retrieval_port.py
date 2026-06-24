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

        evidence_chunks = _dedupe_chunks((*result.child_chunks, *result.ref_chunks, *result.parent_chunks))
        packs = tuple(_chunk_to_evidence_pack(chunk) for chunk in evidence_chunks)
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


def _dedupe_chunks(chunks: tuple[PaperChunk, ...]) -> tuple[PaperChunk, ...]:
    seen: set[str] = set()
    result: list[PaperChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        result.append(chunk)
    return tuple(result)


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
            "parent_chunk_id": chunk.parent_chunk_id,
            "has_formula": chunk.has_formula,
            "formula_latex": chunk.formula_latex,
            "has_figure": chunk.has_figure,
            "figure_id": chunk.figure_id,
            "has_table": chunk.has_table,
            "table_id": chunk.metadata.get("table_id", ""),
            "image_ref": chunk.metadata.get("image_ref", ""),
            "source_locator": chunk.metadata.get("source_locator", ""),
            "caption_source_locator": chunk.metadata.get("caption_source_locator", ""),
            "page": chunk.metadata.get("page"),
            "pdf_rect": chunk.metadata.get("pdf_rect"),
            "caption_pdf_rect": chunk.metadata.get("caption_pdf_rect"),
            "content_sources": chunk.metadata.get("content_sources", []),
            "ocr_attempted": chunk.metadata.get("ocr_attempted", False),
            "ocr_chars": chunk.metadata.get("ocr_chars", 0),
            "ocr_error": chunk.metadata.get("ocr_error", ""),
            "ocr_text_source": chunk.metadata.get("ocr_text_source", ""),
            "text_score": chunk.metadata.get("text_score"),
            "visual_score": chunk.metadata.get("visual_score"),
            "fused_score": chunk.metadata.get("fused_score"),
            "fusion_strategy": chunk.metadata.get("fusion_strategy", ""),
            "visual_hit": chunk.metadata.get("visual_hit", False),
            "expanded_from_chunk_id": chunk.metadata.get("expanded_from_chunk_id", ""),
            "expansion_reason": chunk.metadata.get("expansion_reason", ""),
            "expansion_edge": chunk.metadata.get("expansion_edge", ""),
            "expansion_rank": chunk.metadata.get("expansion_rank"),
            "table_context_rerank_score": chunk.metadata.get("table_context_rerank_score"),
            "table_context_rerank_strategy": chunk.metadata.get("table_context_rerank_strategy", ""),
            "parent_expansion_reason": chunk.metadata.get("parent_expansion_reason", ""),
            "parent_anchor_child_id": chunk.metadata.get("parent_anchor_child_id", ""),
            "parent_snippet": chunk.metadata.get("parent_snippet", False),
            "parent_snippet_strategy": chunk.metadata.get("parent_snippet_strategy", ""),
            "source_parent_chunk_id": chunk.metadata.get("source_parent_chunk_id", ""),
            "parent_rerank_score": chunk.metadata.get("parent_rerank_score"),
            "parent_rerank_strategy": chunk.metadata.get("parent_rerank_strategy", ""),
            "parent_child_relevance_score": chunk.metadata.get("parent_child_relevance_score"),
            "parent_relevance_score": chunk.metadata.get("parent_relevance_score"),
            "parent_section_heading_score": chunk.metadata.get("parent_section_heading_score"),
            "parent_position_score": chunk.metadata.get("parent_position_score"),
            "parent_final_score": chunk.metadata.get("parent_final_score"),
            "parent_score_strategy": chunk.metadata.get("parent_score_strategy", ""),
            "parent_score_weights": chunk.metadata.get("parent_score_weights", {}),
            "row_start": chunk.metadata.get("row_start"),
            "row_end": chunk.metadata.get("row_end"),
            "parent_table_chunk_id": chunk.metadata.get("parent_table_chunk_id", ""),
            "is_table_row_group": chunk.metadata.get("is_table_row_group", False),
        },
    )


# Verify structural compliance at import time
assert isinstance(PaperChunkRetrievalPort(None), RetrievalPort)  # type: ignore[arg-type]

__all__ = ["PaperChunkRetrievalPort"]
