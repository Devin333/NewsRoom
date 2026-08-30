from __future__ import annotations

from typing import Any

from backend.research.document.chunk_storage import PaperChunkStoreAdapter, _chunk_to_payload
from backend.research.document.models import PaperChunk
from infrastructure.storage.vector.fake_store import InMemoryVectorStore
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore


def _chunk(
    chunk_id: str,
    *,
    paper_id: str = "p1",
    content: str = "Transformer attention.",
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    chunk_metadata = {"source_ref": f"paper://{paper_id}/{chunk_id}"}
    if metadata:
        chunk_metadata.update(metadata)
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content=content,
        metadata=chunk_metadata,
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


def test_paper_chunk_payload_does_not_promote_legacy_workflow_identity() -> None:
    payload = _chunk_to_payload(_chunk("legacy-metadata", metadata={"workflow_id": "legacy"}))

    assert payload["metadata"]["workflow_id"] == "legacy"
    assert "workflow_id" not in payload


def test_paper_chunk_store_adapter_tenant_filter_keeps_public_chunks() -> None:
    adapter = PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))
    adapter.ensure_collection()
    adapter.index_chunks([
        _chunk("public"),
        _chunk("tenant-a", metadata={"tenant_id": "tenant-a"}),
        _chunk("tenant-b", metadata={"tenant_id": "tenant-b"}),
    ])

    chunks = adapter.search_chunks(
        "p1",
        "Transformer attention",
        filters={"tenant_id": "tenant-a"},
        limit=3,
    )

    assert {chunk.chunk_id for chunk in chunks} == {"public", "tenant-a"}


def test_paper_chunk_store_uses_configured_collection() -> None:
    vector_store = InMemoryVectorStore()
    adapter = PaperChunkStoreAdapter(
        PaperChunkStore(vector_store, collection="research-run-chunks")
    )
    adapter.ensure_collection()
    adapter.index_chunks([_chunk("custom-collection")])

    assert [chunk.chunk_id for chunk in adapter.list_chunks("p1")] == [
        "custom-collection"
    ]
    assert "research-run-chunks" in vector_store._collections
    assert "paper_chunks" not in vector_store._collections


def test_paper_chunk_store_filters_same_paper_by_run_id() -> None:
    adapter = PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))
    adapter.ensure_collection()
    adapter.index_chunks(
        [
            _chunk("run-a", metadata={"run_id": "run-a"}),
            _chunk("run-b", metadata={"run_id": "run-b"}),
        ]
    )

    chunks = adapter.search_chunks(
        "p1",
        "Transformer attention",
        filters={"run_id": "run-a"},
        limit=3,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["run-a"]


def test_public_search_overfetches_past_tenant_scoped_results() -> None:
    adapter = PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))
    adapter.ensure_collection()
    adapter.index_chunks(
        [
            *[
                _chunk(f"tenant-{index}", metadata={"tenant_id": "tenant-a"})
                for index in range(40)
            ],
            _chunk("public"),
        ]
    )

    chunks = adapter.search_chunks("p1", "Transformer attention", limit=1)

    assert [chunk.chunk_id for chunk in chunks] == ["public"]


def test_tenant_search_paginates_past_arbitrarily_many_hidden_results() -> None:
    adapter = PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))
    adapter.ensure_collection()
    adapter.index_chunks(
        [
            *[
                _chunk(f"hidden-{index}", metadata={"tenant_id": "tenant-b"})
                for index in range(70)
            ],
            _chunk("public"),
            _chunk("tenant-a", metadata={"tenant_id": "tenant-a"}),
        ]
    )

    chunks = adapter.search_chunks(
        "p1",
        "Transformer attention",
        filters={"tenant_id": "tenant-a"},
        limit=2,
    )
    scored = adapter.search_with_scores(
        "p1",
        "Transformer attention",
        filters={"tenant_id": "tenant-a"},
        limit=2,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["public", "tenant-a"]
    assert [chunk.chunk_id for chunk, _score in scored] == ["public", "tenant-a"]


def test_paper_id_filter_cannot_override_authoritative_paper_scope() -> None:
    adapter = PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))
    adapter.ensure_collection()
    adapter.index_chunks(
        [
            _chunk("paper-1", paper_id="p1"),
            _chunk("paper-2", paper_id="p2"),
        ]
    )

    assert adapter.search_chunks(
        "p1",
        "Transformer attention",
        filters={"paper_id": "p2"},
    ) == []
    assert adapter.search_with_scores(
        "p1",
        "Transformer attention",
        filters={"paper_id": "p2"},
    ) == []
