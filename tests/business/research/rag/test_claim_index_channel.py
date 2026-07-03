from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.channels.claim_index import ClaimIndexChannel
from business.research.rag.retrieval.paper_claim_index import ClaimRecord, ClaimSearchHit


def _chunk(chunk_id: str, *, paper_id: str = "p1") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content="The paper makes a supported claim.",
        metadata={},
    )


def _hit(chunk_id: str, score: float, *, paper_id: str = "p1") -> ClaimSearchHit:
    return ClaimSearchHit(
        record=ClaimRecord(
            claim_id=f"claim-{chunk_id}",
            paper_id=paper_id,
            chunk_id=chunk_id,
            claim_text="The model improves accuracy.",
            claim_type="result",
            section_title="Experiments",
            source_locator="paper://p1#page=2",
        ),
        score=score,
    )


class _ChunkStore:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)


class _ClaimIndex:
    def __init__(self, hits: list[ClaimSearchHit]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def search_claims(self, paper_id: str, query_text: str, *, limit: int) -> list[ClaimSearchHit]:
        self.calls.append({"paper_id": paper_id, "query_text": query_text, "limit": limit})
        return self.hits[:limit]


class _FailingClaimIndex:
    def search_claims(self, *args: Any, **kwargs: Any) -> list[ClaimSearchHit]:
        raise RuntimeError("claim index unavailable")


def test_claim_channel_searches_claim_index() -> None:
    hit = _hit("para-1", 0.91)
    index = _ClaimIndex([hit])

    hits = ClaimIndexChannel(_ChunkStore([]), index).search_hits(
        paper_id="p1",
        query_text="supported claim",
        limit=3,
    )

    assert hits == [hit]
    assert index.calls == [{"paper_id": "p1", "query_text": "supported claim", "limit": 3}]


def test_claim_channel_search_failure_returns_empty() -> None:
    hits = ClaimIndexChannel(_ChunkStore([]), _FailingClaimIndex()).search_hits(
        paper_id="p1",
        query_text="supported claim",
        limit=3,
    )

    assert hits == []


def test_claim_channel_merges_claim_metadata_and_scores() -> None:
    chunk = _chunk("para-1")
    hit = _hit("para-1", 0.91)

    merged = ClaimIndexChannel(_ChunkStore([chunk]), None).merge_hits(
        [(chunk, 0.2)],
        [hit],
        "p1",
    )

    assert merged[0][1] == 0.91
    metadata = merged[0][0].metadata
    assert metadata["claim_index_hit"] is True
    assert metadata["claim_index_score"] == 0.91
    assert metadata["claim_id"] == "claim-para-1"
    assert metadata["claim_text"] == "The model improves accuracy."


def test_claim_channel_ranks_chunks_by_claim_score() -> None:
    weak = _chunk("weak")
    strong = _chunk("strong")

    ranked = ClaimIndexChannel(_ChunkStore([weak, strong]), None).ranked_chunks(
        [_hit("weak", 0.2), _hit("strong", 0.9)],
        "p1",
    )

    assert [chunk.chunk_id for chunk, _score in ranked] == ["strong", "weak"]
