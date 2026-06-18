from __future__ import annotations

from typing import Any

from qdrant_client import models as qmodels

from infrastructure.storage.vector.models import VectorDocument, VectorSearchQuery
from infrastructure.storage.vector.qdrant_store import QdrantVectorStore

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
    """
    Qdrant-backed payload store for paper chunks. Implements ChunkPayloadStorePort.
    Speaks raw payload dicts only — no domain-DTO dependency. A business-layer
    adapter converts payloads ↔ PaperChunk.

    Each payload dict must carry 'chunk_id', 'paper_id' and 'content'.
    """

    def __init__(self, vector_store: QdrantVectorStore) -> None:
        self._store = vector_store

    def ensure_collection(self) -> None:
        self._store.ensure_collections([PAPER_CHUNKS_COLLECTION])
        self._store.ensure_payload_indexes([PAPER_CHUNKS_COLLECTION], _PAYLOAD_INDEXES)

    def index_payloads(self, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        self._store.upsert_documents([_payload_to_doc(p) for p in payloads])

    def delete_paper_chunks(self, paper_id: str) -> None:
        self._store.client.delete(
            collection_name=PAPER_CHUNKS_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="paper_id", match=qmodels.MatchValue(value=paper_id))]
                )
            ),
        )

    def search_payloads_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[dict[str, Any], float]]:
        combined: dict[str, Any] = {"paper_id": paper_id, **(filters or {})}
        results = self._store.search(VectorSearchQuery(
            collection=PAPER_CHUNKS_COLLECTION,
            text=query_text,
            filters=combined,
            limit=limit,
        ))
        return [(dict(r.payload), r.score) for r in results]

    def search_payloads(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        combined: dict[str, Any] = {"paper_id": paper_id, **(filters or {})}
        results = self._store.search(VectorSearchQuery(
            collection=PAPER_CHUNKS_COLLECTION,
            text=query_text,
            filters=combined,
            limit=limit,
            score_threshold=score_threshold,
        ))
        return [dict(r.payload) for r in results]

    def get_payload(self, chunk_id: str) -> dict[str, Any] | None:
        result = self._store.get_document(PAPER_CHUNKS_COLLECTION, chunk_id)
        return dict(result.payload) if result else None


def _payload_to_doc(payload: dict[str, Any]) -> VectorDocument:
    return VectorDocument(
        document_id=str(payload["chunk_id"]),
        collection=PAPER_CHUNKS_COLLECTION,
        text=str(payload["content"]),
        payload=dict(payload),
        source_type="paper_chunk",
        topic=str(payload["paper_id"]),
        section_id=str(payload["chunk_id"]),
    )


__all__ = ["PAPER_CHUNKS_COLLECTION", "PaperChunkStore"]
