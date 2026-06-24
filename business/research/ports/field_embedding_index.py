from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from business.research.document.models import PaperChunk

FieldName = str


@dataclass(frozen=True)
class FieldEmbeddingHit:
    chunk_id: str
    field_name: FieldName
    score: float
    field_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class FieldEmbeddingIndexerPort(Protocol):
    def ensure_collection(self) -> None: ...

    def index_chunks(self, chunks: list[PaperChunk]) -> None: ...

    def delete_paper_chunks(self, paper_id: str) -> None: ...


@runtime_checkable
class FieldEmbeddingSearchPort(Protocol):
    def search_field_vectors(
        self,
        paper_id: str,
        query_text: str,
        *,
        field_names: tuple[FieldName, ...] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[FieldEmbeddingHit]: ...


@runtime_checkable
class FieldEmbeddingIndexPort(FieldEmbeddingIndexerPort, FieldEmbeddingSearchPort, Protocol):
    pass


__all__ = [
    "FieldEmbeddingHit",
    "FieldEmbeddingIndexerPort",
    "FieldEmbeddingIndexPort",
    "FieldEmbeddingSearchPort",
    "FieldName",
]
