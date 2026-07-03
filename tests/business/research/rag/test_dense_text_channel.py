from __future__ import annotations

from typing import Any

import pytest

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.channels.dense_text import DenseTextChannel


def _chunk(chunk_id: str, content: str = "Dense text candidate.") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content=content,
        metadata={},
    )


class _SearchStore:
    def __init__(self, hits: list[tuple[PaperChunk, float]]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[tuple[PaperChunk, float]]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "filters": filters,
            "limit": limit,
        })
        return self.hits[:limit]


class _FailingStore:
    def search_with_scores(self, *args: Any, **kwargs: Any) -> list[tuple[PaperChunk, float]]:
        raise RuntimeError("dense unavailable")


def test_dense_text_channel_returns_search_scores() -> None:
    chunk = _chunk("para-1")
    store = _SearchStore([(chunk, 0.87)])

    hits = DenseTextChannel(store).recall_chunks(  # type: ignore[arg-type]
        paper_id="p1",
        query_text="attention",
        filters={"chunk_type": "paragraph"},
        limit=5,
    )

    assert hits == [(chunk, 0.87)]
    assert store.calls == [
        {
            "paper_id": "p1",
            "query_text": "attention",
            "filters": {"chunk_type": "paragraph"},
            "limit": 5,
        }
    ]


def test_dense_text_channel_can_suppress_hybrid_failures() -> None:
    channel = DenseTextChannel(_FailingStore())  # type: ignore[arg-type]

    assert channel.recall_chunks(
        paper_id="p1",
        query_text="attention",
        filters={},
        limit=5,
        suppress_errors=True,
    ) == []

    with pytest.raises(RuntimeError, match="dense unavailable"):
        channel.recall_chunks(
            paper_id="p1",
            query_text="attention",
            filters={},
            limit=5,
            suppress_errors=False,
        )
