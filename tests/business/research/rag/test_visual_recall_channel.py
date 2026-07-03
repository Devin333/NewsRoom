from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.paper_visual_retrieval import PaperVisualFusionWeights


def _chunk(chunk_id: str, *, paper_id: str = "p1") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="figure",
        section_title="Experiments",
        section_role=["experiment"],
        section_index=2,
        content="Figure caption.",
        metadata={},
    )


class _ChunkStore:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)


class _VisualStore:
    def __init__(self, hits: list[VisualChunkHit]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def search_visual_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[VisualChunkHit]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "filters": filters,
            "limit": limit,
        })
        return self.hits[:limit]


class _FailingVisualStore:
    def search_visual_chunks(self, *args: Any, **kwargs: Any) -> list[VisualChunkHit]:
        raise RuntimeError("visual unavailable")


def test_visual_channel_searches_and_deduplicates_by_chunk() -> None:
    lower = VisualChunkHit("fig-1", 0.4)
    higher = VisualChunkHit("fig-1", 0.9)
    other = VisualChunkHit("fig-2", 0.7)
    store = _VisualStore([lower, higher, other])

    hits = VisualRecallChannel(_ChunkStore([]), store).search_hits(
        paper_id="p1",
        query_text="architecture figure",
        candidate_filters=[{"chunk_type": "figure"}],
        limit=10,
    )

    assert hits == [higher, other]
    assert store.calls == [
        {
            "paper_id": "p1",
            "query_text": "architecture figure",
            "filters": {"chunk_type": "figure"},
            "limit": 10,
        }
    ]


def test_visual_channel_search_failure_returns_empty() -> None:
    hits = VisualRecallChannel(_ChunkStore([]), _FailingVisualStore()).search_hits(
        paper_id="p1",
        query_text="architecture figure",
        candidate_filters=[{}],
        limit=10,
    )

    assert hits == []


def test_visual_channel_fuses_text_and_visual_scores() -> None:
    text_chunk = _chunk("fig-1")
    visual_chunk = _chunk("fig-2")
    channel = VisualRecallChannel(_ChunkStore([text_chunk, visual_chunk]), None)

    fused = channel.fuse_scores(
        [(text_chunk, 0.5)],
        [VisualChunkHit("fig-1", 1.0), VisualChunkHit("fig-2", 0.8)],
        paper_id="p1",
        weights=PaperVisualFusionWeights(text=0.75, visual=0.25),
    )

    by_id = {chunk.chunk_id: (chunk, score) for chunk, score in fused}
    assert by_id["fig-1"][1] == 0.625
    assert by_id["fig-1"][0].metadata["visual_score"] == 1.0
    assert by_id["fig-1"][0].metadata["fusion_strategy"] == "text_image_fusion"
    assert by_id["fig-2"][1] == 0.2
    assert by_id["fig-2"][0].metadata["fusion_strategy"] == "image_only"


def test_visual_channel_ranks_chunks_by_visual_score() -> None:
    weak = _chunk("weak")
    strong = _chunk("strong")

    ranked = VisualRecallChannel(_ChunkStore([weak, strong]), None).ranked_chunks(
        [VisualChunkHit("weak", 0.2), VisualChunkHit("strong", 0.9)],
        "p1",
    )

    assert [chunk.chunk_id for chunk, _score in ranked] == ["strong", "weak"]
    assert ranked[0][0].metadata["fusion_strategy"] == "visual_channel_rrf"
