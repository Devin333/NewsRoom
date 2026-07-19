from __future__ import annotations

from typing import Any

from qdrant_client import models as qmodels

from infrastructure.storage.vector.models import VectorDocument, VectorSearchQuery
from infrastructure.storage.vector.qdrant_store import QdrantVectorStore

PAPER_CHUNKS_COLLECTION = "paper_chunks"

_PAYLOAD_INDEXES: dict[str, str] = {
    "paper_id": "keyword",
    "run_id": "keyword",
    "session_id": "keyword",
    "user_id": "keyword",
    "chunk_type": "keyword",
    "has_formula": "bool",
    "has_figure": "bool",
    "has_table": "bool",
    "figure_id": "keyword",
    "tenant": "keyword",
    "tenant_id": "keyword",
    "propositions_generated": "bool",
    "structure_detected": "bool",
    "section_index": "integer",
    "workspace_id": "keyword",
}


class PaperChunkStore:
    """
    Qdrant-backed payload store for paper chunks. Implements ChunkPayloadStorePort.
    Speaks raw payload dicts only — no domain-DTO dependency. A business-layer
    adapter converts payloads ↔ PaperChunk.

    Each payload dict must carry 'chunk_id', 'paper_id' and 'content'.
    """

    def __init__(
        self,
        vector_store: QdrantVectorStore,
        *,
        collection: str = PAPER_CHUNKS_COLLECTION,
    ) -> None:
        self._store = vector_store
        self._collection = str(collection).strip()
        if not self._collection:
            raise ValueError("paper chunk collection is required")

    def ensure_collection(self) -> None:
        self._store.ensure_collections([self._collection])
        self._store.ensure_payload_indexes([self._collection], _PAYLOAD_INDEXES)

    def index_payloads(self, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        self._store.upsert_documents(
            [_payload_to_doc(p, collection=self._collection) for p in payloads]
        )

    def delete_paper_chunks(self, paper_id: str) -> None:
        self._store.client.delete(
            collection_name=self._collection,
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
        offset: int = 0,
    ) -> list[tuple[dict[str, Any], float]]:
        combined = _paper_scoped_filters(paper_id, filters)
        if combined is None:
            return []
        results = self._store.search(VectorSearchQuery(
            collection=self._collection,
            text=query_text,
            filters=combined,
            limit=limit,
            offset=offset,
        ))
        return [(dict(r.payload), r.score) for r in results]

    def search_payloads(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        combined = _paper_scoped_filters(paper_id, filters)
        if combined is None:
            return []
        results = self._store.search(VectorSearchQuery(
            collection=self._collection,
            text=query_text,
            filters=combined,
            limit=limit,
            offset=offset,
            score_threshold=score_threshold,
        ))
        return [dict(r.payload) for r in results]

    def get_payload(self, chunk_id: str) -> dict[str, Any] | None:
        result = self._store.get_document(self._collection, chunk_id)
        return dict(result.payload) if result else None

    def list_paper_payloads(self, paper_id: str) -> list[dict[str, Any]]:
        return self._store.list_payloads(
            self._collection,
            filters={"paper_id": paper_id},
        )


def _payload_to_doc(
    payload: dict[str, Any],
    *,
    collection: str = PAPER_CHUNKS_COLLECTION,
) -> VectorDocument:
    return VectorDocument(
        document_id=str(payload["chunk_id"]),
        collection=collection,
        text=str(payload["content"]),
        payload=dict(payload),
        source_type="paper_chunk",
        topic=str(payload["paper_id"]),
        section_id=str(payload["chunk_id"]),
    )


def _paper_scoped_filters(
    paper_id: str,
    filters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    selected = dict(filters or {})
    if "paper_id" in selected and selected["paper_id"] != paper_id:
        return None
    selected["paper_id"] = paper_id
    return selected


__all__ = ["PAPER_CHUNKS_COLLECTION", "PaperChunkStore"]
