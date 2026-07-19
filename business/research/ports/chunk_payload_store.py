from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChunkPayloadStorePort(Protocol):
    """
    Storage-facing vector store contract — speaks raw payload dicts, not domain DTOs.
    Each payload must carry at least 'chunk_id', 'paper_id' and 'content' keys.
    Implemented by infrastructure (Qdrant); wrapped by a business-layer adapter
    that converts payloads ↔ PaperChunk.
    """

    def ensure_collection(self) -> None: ...

    def index_payloads(self, payloads: list[dict[str, Any]]) -> None: ...

    def delete_paper_chunks(self, paper_id: str) -> None: ...

    def search_payloads_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[tuple[dict[str, Any], float]]: ...

    def search_payloads(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_payload(self, chunk_id: str) -> dict[str, Any] | None: ...
    def list_paper_payloads(self, paper_id: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class ChunkPayloadRepositoryPort(Protocol):
    """Storage-facing relational contract — payload dicts in, payload dicts out."""

    def save_payloads(self, payloads: list[dict[str, Any]]) -> None: ...
    def list_paper_chunks(self, paper_id: str) -> list[dict[str, Any]]: ...
    def delete_paper_chunks(self, paper_id: str) -> None: ...


__all__ = ["ChunkPayloadRepositoryPort", "ChunkPayloadStorePort"]
