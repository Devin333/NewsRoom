from __future__ import annotations

import json

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.bm25_index import (
    PaperBM25Index,
    load_bm25_index,
    write_bm25_index,
)


def _chunk(chunk_id: str, content: str, *, paper_id: str = "p1") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content=content,
        metadata={},
    )


def test_bm25_index_ranks_rare_term_match_first() -> None:
    index = PaperBM25Index.build(
        "p1",
        [
            _chunk("generic", "The method reports generic benchmark results."),
            _chunk("rare", "The ablation reports raremetric42 accuracy gains."),
        ],
    )

    hits = index.search("Which result mentions raremetric42?", limit=2)

    assert [hit.chunk.chunk_id for hit in hits] == ["rare"]
    assert hits[0].score > 0.0


def test_bm25_index_persists_postings_and_roundtrips(tmp_path) -> None:
    target = tmp_path / "bm25_index.json"
    write_bm25_index(
        "p1",
        [
            _chunk("generic", "The method reports generic benchmark results."),
            _chunk("rare", "The ablation reports raremetric42 accuracy gains."),
        ],
        target,
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    loaded = load_bm25_index("p1", target)

    assert payload["paper_id"] == "p1"
    assert "raremetric42" in payload["postings"]
    assert loaded.search("raremetric42", limit=1)[0].chunk.chunk_id == "rare"
