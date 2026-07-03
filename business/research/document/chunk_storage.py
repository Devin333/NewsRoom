from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.chunk_payload_store import (
    ChunkPayloadRepositoryPort,
    ChunkPayloadStorePort,
)

_CHUNK_FIELDS = set(PaperChunk.model_fields.keys())


def _chunk_to_payload(chunk: PaperChunk) -> dict[str, Any]:
    return chunk.model_dump(mode="json")


def _payload_to_chunk(payload: dict[str, Any]) -> PaperChunk | None:
    # storage backends may add canonical fields (VectorDocument); PrimitiveModel
    # uses extra="forbid", so keep only PaperChunk's own fields before validating.
    try:
        return PaperChunk.model_validate({k: v for k, v in payload.items() if k in _CHUNK_FIELDS})
    except Exception:
        return None


class PaperChunkStoreAdapter:
    """
    Business-layer adapter implementing ChunkStorePort + ChunkIndexerPort.
    Wraps a storage-facing ChunkPayloadStorePort and converts PaperChunk ↔ payload,
    keeping the domain DTO out of the infrastructure layer.
    """

    def __init__(self, payload_store: ChunkPayloadStorePort) -> None:
        self._store = payload_store

    # ── ChunkStorePort ───────────────────────────────────────────────────────

    def ensure_collection(self) -> None:
        self._store.ensure_collection()

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        payloads = self._store.search_payloads(
            paper_id, query_text, filters=filters, limit=limit, score_threshold=score_threshold
        )
        return [c for p in payloads if (c := _payload_to_chunk(p)) is not None]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        scored = self._store.search_payloads_with_scores(
            paper_id, query_text, filters=filters, limit=limit
        )
        out: list[tuple[PaperChunk, float]] = []
        for payload, score in scored:
            chunk = _payload_to_chunk(payload)
            if chunk is not None:
                out.append((chunk, score))
        return out

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        payload = self._store.get_payload(chunk_id)
        return _payload_to_chunk(payload) if payload else None

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return self.get_chunk(chunk.parent_chunk_id) if chunk.parent_chunk_id else None

    # ── ChunkIndexerPort ───────────────────────────────────────────────────────

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        return [c for p in self._store.list_paper_payloads(paper_id) if (c := _payload_to_chunk(p)) is not None]

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        self._store.index_payloads([_chunk_to_payload(c) for c in chunks])

    def delete_paper_chunks(self, paper_id: str) -> None:
        self._store.delete_paper_chunks(paper_id)


class PaperChunkRepositoryAdapter:
    """
    Business-layer adapter implementing ChunkRepositoryPort.
    Wraps a storage-facing ChunkPayloadRepositoryPort, converting PaperChunk ↔ payload.
    """

    def __init__(self, payload_repo: ChunkPayloadRepositoryPort) -> None:
        self._repo = payload_repo

    def save_chunks(self, chunks: list[PaperChunk]) -> None:
        self._repo.save_payloads([_chunk_to_payload(c) for c in chunks])

    def delete_paper_chunks(self, paper_id: str) -> None:
        self._repo.delete_paper_chunks(paper_id)

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        return [c for p in self._repo.list_paper_chunks(paper_id) if (c := _payload_to_chunk(p)) is not None]

    def list_paper_chunks(self, paper_id: str) -> list[dict[str, Any]]:
        return self._repo.list_paper_chunks(paper_id)


__all__ = ["PaperChunkRepositoryAdapter", "PaperChunkStoreAdapter"]
