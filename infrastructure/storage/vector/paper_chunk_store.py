from __future__ import annotations

from typing import Any

from qdrant_client import models as qmodels

from infrastructure.storage.vector.models import VectorDocument, VectorSearchQuery
from infrastructure.storage.vector.qdrant_store import QdrantVectorStore
from business.research.document.models import PaperChunk

PAPER_CHUNKS_COLLECTION = "paper_chunks"

_PAYLOAD_INDEXES: dict[str, str] = {
    "paper_id": "keyword",
    "chunk_type": "keyword",
    "has_formula": "bool",
    "has_figure": "bool",
    "has_table": "bool",
    "figure_id": "keyword",
    "propositions_generated": "bool",
    "structure_detected": "bool",
    "section_index": "integer",
}


class PaperChunkStore:
    """Qdrant-backed store for paper chunks. Implements ChunkIndexerPort + ChunkStorePort."""

    def __init__(self, vector_store: QdrantVectorStore) -> None:
        self._store = vector_store

    def ensure_collection(self) -> None:
        self._store.ensure_collections([PAPER_CHUNKS_COLLECTION])
        self._store.ensure_payload_indexes([PAPER_CHUNKS_COLLECTION], _PAYLOAD_INDEXES)

    # ── ChunkIndexerPort ─────────────────────────────────────────────────────

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        if not chunks:
            return
        self._store.upsert_documents([_chunk_to_doc(c) for c in chunks])

    def delete_paper_chunks(self, paper_id: str) -> None:
        self._store.client.delete(
            collection_name=PAPER_CHUNKS_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="paper_id", match=qmodels.MatchValue(value=paper_id))]
                )
            ),
        )

    # ── ChunkStorePort ───────────────────────────────────────────────────────

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        """Return (chunk, semantic_score) pairs for position-aware re-ranking."""
        combined: dict[str, Any] = {"paper_id": paper_id, **(filters or {})}
        results = self._store.search(VectorSearchQuery(
            collection=PAPER_CHUNKS_COLLECTION,
            text=query_text,
            filters=combined,
            limit=limit,
        ))
        out: list[tuple[PaperChunk, float]] = []
        for r in results:
            chunk = _payload_to_chunk(r.payload)
            if chunk is not None:
                out.append((chunk, r.score))
        return out

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        combined: dict[str, Any] = {"paper_id": paper_id, **(filters or {})}
        results = self._store.search(VectorSearchQuery(
            collection=PAPER_CHUNKS_COLLECTION,
            text=query_text,
            filters=combined,
            limit=limit,
            score_threshold=score_threshold,
        ))
        return [c for r in results if (c := _payload_to_chunk(r.payload)) is not None]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        result = self._store.get_document(PAPER_CHUNKS_COLLECTION, chunk_id)
        return _payload_to_chunk(result.payload) if result else None

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return self.get_chunk(chunk.parent_chunk_id) if chunk.parent_chunk_id else None


def _chunk_to_doc(chunk: PaperChunk) -> VectorDocument:
    return VectorDocument(
        document_id=chunk.chunk_id,
        collection=PAPER_CHUNKS_COLLECTION,
        text=chunk.content,
        payload=chunk.model_dump(),
        source_type="paper_chunk",
        topic=chunk.paper_id,
        section_id=chunk.chunk_id,
    )


def _payload_to_chunk(payload: dict[str, Any]) -> PaperChunk | None:
    # PrimitiveModel uses extra="forbid"; strip VectorDocument canonical fields before validating
    _CHUNK_FIELDS = PaperChunk.model_fields.keys()
    try:
        return PaperChunk.model_validate({k: v for k, v in payload.items() if k in _CHUNK_FIELDS})
    except Exception:
        return None


__all__ = ["PAPER_CHUNKS_COLLECTION", "PaperChunkStore"]
