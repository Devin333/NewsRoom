from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.rag.retrieval.channels.field_embedding import FieldEmbeddingChannel


def _chunk(chunk_id: str, *, paper_id: str = "p1") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content="The paper describes attention.",
        metadata={},
    )


def _hit(
    chunk_id: str,
    field_name: str,
    score: float,
    *,
    field_text: str = "field text",
) -> FieldEmbeddingHit:
    return FieldEmbeddingHit(
        chunk_id=chunk_id,
        field_name=field_name,
        score=score,
        field_text=field_text,
        metadata={"source_locator": "paper://p1#page=2"},
    )


class _ChunkStore:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)


class _FieldIndex:
    def __init__(self, hits: list[FieldEmbeddingHit]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def search_field_vectors(
        self,
        paper_id: str,
        query_text: str,
        *,
        field_names: tuple[str, ...] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[FieldEmbeddingHit]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "field_names": field_names,
            "filters": filters,
            "limit": limit,
        })
        return self.hits[:limit]


class _FailingFieldIndex:
    def search_field_vectors(self, *args: Any, **kwargs: Any) -> list[FieldEmbeddingHit]:
        raise RuntimeError("field index unavailable")


def test_field_channel_searches_and_deduplicates_by_chunk_and_field() -> None:
    lower = _hit("para-1", "caption", 0.4)
    higher = _hit("para-1", "caption", 0.9)
    body = _hit("para-1", "body", 0.7)
    index = _FieldIndex([lower, higher, body])

    hits = FieldEmbeddingChannel(_ChunkStore([]), index).search_hits(
        paper_id="p1",
        query_text="attention",
        field_names=("caption", "body"),
        candidate_filters=[{"chunk_type": "paragraph"}],
        limit=10,
    )

    assert hits == [higher, body]
    assert index.calls == [
        {
            "paper_id": "p1",
            "query_text": "attention",
            "field_names": ("caption", "body"),
            "filters": {"chunk_type": "paragraph"},
            "limit": 10,
        }
    ]


def test_field_channel_search_failure_returns_empty() -> None:
    hits = FieldEmbeddingChannel(_ChunkStore([]), _FailingFieldIndex()).search_hits(
        paper_id="p1",
        query_text="attention",
        field_names=("caption",),
        candidate_filters=[{}],
        limit=10,
    )

    assert hits == []


def test_field_channel_merges_field_metadata() -> None:
    chunk = _chunk("para-1")

    merged = FieldEmbeddingChannel(_ChunkStore([chunk]), None).merge_hits(
        [(chunk, 0.2)],
        [_hit("para-1", "caption", 0.87, field_text="Caption content for the figure.")],
        "p1",
    )

    metadata = merged[0][0].metadata
    assert merged[0][1] == 0.2
    assert metadata["field_embedding_scores"] == {"caption": 0.87}
    assert metadata["caption_embedding_score"] == 0.87
    assert metadata["field_embedding_score"] == 0.87
    assert metadata["best_embedding_field"] == "caption"
    assert metadata["field_embedding_hits"][0]["field_text_preview"] == "Caption content for the figure."


def test_field_channel_ranks_chunks_by_best_field_score() -> None:
    weak = _chunk("weak")
    strong = _chunk("strong")

    ranked = FieldEmbeddingChannel(_ChunkStore([weak, strong]), None).ranked_chunks(
        [_hit("weak", "body", 0.2), _hit("strong", "caption", 0.9)],
        "p1",
    )

    assert [chunk.chunk_id for chunk, _score in ranked] == ["strong", "weak"]
    assert ranked[0][0].metadata["best_embedding_field"] == "caption"
