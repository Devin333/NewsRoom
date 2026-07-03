from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval.contracts import RetrievalRequest
from business.research.rag.retrieval.factory import build_retrieval_pipeline
from business.research.rag.retrieval.policies import RetrievalPolicy


def _chunk(chunk_id: str, *, chunk_type: str = "figure") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Figures",
        section_role=["experiment"],  # type: ignore[arg-type]
        section_index=2,
        content="Architecture figure caption.",
        metadata={},
    )


class _ChunkStore:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def ensure_collection(self) -> None:
        return None

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        return [chunk for chunk, _score in self.search_with_scores(
            paper_id,
            query_text,
            filters=filters,
            limit=limit,
        )]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        out: list[tuple[PaperChunk, float]] = []
        for chunk in self._chunks.values():
            if chunk.paper_id != paper_id:
                continue
            if filters and any(getattr(chunk, key, chunk.metadata.get(key)) != value for key, value in filters.items()):
                continue
            out.append((chunk, 0.5))
            if len(out) >= limit:
                break
        return out

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return None

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        return [chunk for chunk in self._chunks.values() if chunk.paper_id == paper_id]


class _VisualStore:
    def search_visual_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[VisualChunkHit]:
        return [VisualChunkHit("fig-1", 0.9)]


def test_factory_builds_pipeline_and_preserves_optional_adapter_metadata() -> None:
    pipeline = build_retrieval_pipeline(
        _ChunkStore([_chunk("fig-1")]),
        policy=RetrievalPolicy(overfetch_multiplier=1),
        visual_store=_VisualStore(),
    )

    result = pipeline.retrieve(
        RetrievalRequest(paper_id="p1", question="What does Figure 1 architecture show?", limit=1)
    )

    assert result.child_chunks[0].chunk_id == "fig-1"
    assert result.metadata["visual_fusion_enabled"] is True
    assert result.metadata["field_embedding_enabled"] is False
    assert result.metadata["claim_index_enabled"] is False
    assert result.child_chunks[0].metadata["visual_hit"] is True
