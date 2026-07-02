from __future__ import annotations

from business.research.document.chunk_storage import PaperChunkStoreAdapter
from business.research.document.models import PaperChunk
from infrastructure.storage.vector.fake_store import InMemoryVectorStore
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore


def _chunk(chunk_id: str, *, paper_id: str = "p1", content: str = "Transformer attention.") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content=content,
        metadata={"source_ref": f"paper://{paper_id}/{chunk_id}"},
    )


def test_paper_chunk_store_adapter_lists_paper_chunks_from_vector_payloads() -> None:
    adapter = PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))
    adapter.ensure_collection()
    adapter.index_chunks([
        _chunk("p1-a"),
        _chunk("p1-b"),
        _chunk("p2-a", paper_id="p2"),
    ])

    chunks = adapter.list_chunks("p1")

    assert [chunk.chunk_id for chunk in chunks] == ["p1-a", "p1-b"]
    assert all(chunk.paper_id == "p1" for chunk in chunks)
