from __future__ import annotations

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.channels import RankedHit
from business.research.rag.retrieval.fusion import fuse_chunk_rankings, fuse_ranked_hits


def _chunk(chunk_id: str, *, section_index: int = 0, metadata: dict | None = None) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="nougat",
        chunk_type="paragraph",
        content=f"content {chunk_id}",
        section_index=section_index,
        metadata=metadata or {},
    )


def test_ranked_hit_carries_channel_contract() -> None:
    hit = RankedHit(
        chunk_id="c1",
        score=0.9,
        channel="dense_text",
        metadata={"query": "method"},
    )

    assert hit.chunk_id == "c1"
    assert hit.score == 0.9
    assert hit.channel == "dense_text"
    assert hit.metadata["query"] == "method"


def test_fuse_ranked_hits_is_deterministic_and_deduplicates_per_channel() -> None:
    fused = fuse_ranked_hits(
        [
            ("dense", [
                RankedHit("b", 0.8, "dense"),
                RankedHit("a", 0.7, "dense"),
                RankedHit("b", 0.1, "dense"),
            ]),
            ("sparse", [
                RankedHit("a", 0.9, "sparse"),
                RankedHit("b", 0.2, "sparse"),
            ]),
        ],
        limit=10,
        rrf_k=60,
    )

    assert [hit.chunk_id for hit in fused] == ["a", "b"]
    assert fused[0].metadata["rrf_contributions"] == {
        "dense": 0.016129,
        "sparse": 0.016393,
    }


def test_fuse_chunk_rankings_preserves_existing_hybrid_metadata_shape() -> None:
    c1 = _chunk("c1", metadata={"from_dense": True})
    c2 = _chunk("c2", section_index=2)
    c1_sparse = _chunk("c1", metadata={"from_sparse": True})

    fused = fuse_chunk_rankings(
        [
            ("dense:0", [(c1, 0.8), (c2, 0.7)]),
            ("sparse:0", [(c1_sparse, 0.9)]),
        ],
        limit=10,
        rrf_k=60,
        metadata_prefix="text",
    )

    top, score = fused[0]
    assert top.chunk_id == "c1"
    assert score == 1.0
    assert top.metadata["from_dense"] is True
    assert top.metadata["from_sparse"] is True
    assert top.metadata["text_rrf_fusion"] is True
    assert top.metadata["hybrid_rrf_fusion"] is True
    assert top.metadata["text_rrf_channels"] == ["dense:0", "sparse:0"]
