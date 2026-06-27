from __future__ import annotations

from typing import Any

from qdrant_client import models as qmodels

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.rag.adapters.paper_field_text import FIELD_NAMES, extract_field_texts
from infrastructure.storage.vector.models import VectorDocument, VectorSearchQuery
from infrastructure.storage.vector.qdrant_store import QdrantVectorStore

PAPER_FIELD_CHUNKS_COLLECTION = "paper_field_chunks"

_PAYLOAD_INDEXES: dict[str, str] = {
    "paper_id": "keyword",
    "chunk_id": "keyword",
    "field_name": "keyword",
    "chunk_type": "keyword",
    "has_formula": "bool",
    "has_figure": "bool",
    "has_table": "bool",
    "section_index": "integer",
}


class PaperFieldChunkStore:
    """Field-level vector index for paper chunks."""

    def __init__(self, vector_store: QdrantVectorStore | Any) -> None:
        self._store = vector_store

    def ensure_collection(self) -> None:
        self._store.ensure_collections([PAPER_FIELD_CHUNKS_COLLECTION])
        self._store.ensure_payload_indexes([PAPER_FIELD_CHUNKS_COLLECTION], _PAYLOAD_INDEXES)

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        docs: list[VectorDocument] = []
        for chunk in chunks:
            docs.extend(_chunk_to_field_docs(chunk))
        if docs:
            self._store.upsert_documents(docs)

    def delete_paper_chunks(self, paper_id: str) -> None:
        if hasattr(self._store, "delete_by_filter"):
            self._store.delete_by_filter(PAPER_FIELD_CHUNKS_COLLECTION, {"paper_id": paper_id})
            return

        self._store.client.delete(
            collection_name=PAPER_FIELD_CHUNKS_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="paper_id", match=qmodels.MatchValue(value=paper_id))]
                )
            ),
        )

    def search_field_vectors(
        self,
        paper_id: str,
        query_text: str,
        *,
        field_names: tuple[str, ...] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[FieldEmbeddingHit]:
        names = _normalized_field_names(field_names)
        combined_filters = {"paper_id": paper_id, **(filters or {})}
        results = []
        if names:
            for field_name in names:
                results.extend(self._search_one_field(
                    query_text,
                    filters={**combined_filters, "field_name": field_name},
                    limit=limit,
                ))
        else:
            results.extend(self._search_one_field(query_text, filters=combined_filters, limit=limit))

        results.sort(key=lambda hit: hit.score, reverse=True)
        return results[:limit]

    def _search_one_field(
        self,
        query_text: str,
        *,
        filters: dict[str, Any],
        limit: int,
    ) -> list[FieldEmbeddingHit]:
        results = self._store.search(
            VectorSearchQuery(
                collection=PAPER_FIELD_CHUNKS_COLLECTION,
                text=query_text,
                filters=filters,
                limit=limit,
            )
        )
        hits: list[FieldEmbeddingHit] = []
        for result in results:
            chunk_id = result.payload.get("chunk_id")
            field_name = result.payload.get("field_name")
            if not chunk_id or not field_name:
                continue
            hits.append(FieldEmbeddingHit(
                chunk_id=str(chunk_id),
                field_name=str(field_name),
                score=float(result.score),
                field_text=str(result.payload.get("field_text") or result.text or ""),
                metadata=dict(result.payload),
            ))
        return hits


def _chunk_to_field_docs(chunk: PaperChunk) -> list[VectorDocument]:
    field_texts = extract_field_texts(chunk)
    docs: list[VectorDocument] = []
    for field_name, field_text in field_texts.non_empty().items():
        payload = _field_payload(chunk, field_name=field_name, field_text=field_text, sources=field_texts.sources_for(field_name))
        docs.append(VectorDocument(
            document_id=f"{chunk.chunk_id}:{field_name}",
            collection=PAPER_FIELD_CHUNKS_COLLECTION,
            text=field_text,
            payload=payload,
            source_type="paper_chunk_field",
            topic=chunk.paper_id,
            section_id=chunk.chunk_id,
        ))
    return docs


def _field_payload(
    chunk: PaperChunk,
    *,
    field_name: str,
    field_text: str,
    sources: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "paper_id": chunk.paper_id,
        "chunk_id": chunk.chunk_id,
        "field_name": field_name,
        "field_text": field_text,
        "field_text_sources": list(sources),
        "chunk_type": chunk.chunk_type,
        "section_title": chunk.section_title,
        "section_role": list(chunk.section_role),
        "section_index": chunk.section_index,
        "has_formula": chunk.has_formula,
        "has_figure": chunk.has_figure,
        "has_table": chunk.has_table,
        "figure_id": chunk.figure_id,
        "table_id": chunk.metadata.get("table_id", ""),
        "source_locator": chunk.metadata.get("source_locator", ""),
        "caption_source_locator": chunk.metadata.get("caption_source_locator", ""),
        "page": chunk.metadata.get("page"),
        "pdf_rect": chunk.metadata.get("pdf_rect"),
        "caption_pdf_rect": chunk.metadata.get("caption_pdf_rect"),
    }


def _normalized_field_names(field_names: tuple[str, ...] | None) -> tuple[str, ...]:
    if not field_names:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for field_name in field_names:
        normalized = str(field_name).strip().casefold()
        if normalized in FIELD_NAMES and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


__all__ = ["PAPER_FIELD_CHUNKS_COLLECTION", "PaperFieldChunkStore"]
