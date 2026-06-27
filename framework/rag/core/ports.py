from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from framework.rag.core.models import RAGChunk, RAGEvidence, RAGQuery


@runtime_checkable
class RAGChunkStorePort(Protocol):
    def get_chunk(self, chunk_id: str) -> RAGChunk | None:
        ...

    def list_chunks(self, document_id: str) -> Sequence[RAGChunk]:
        ...


@runtime_checkable
class RAGRetrieverPort(Protocol):
    def retrieve(self, query: RAGQuery) -> Sequence[RAGEvidence]:
        ...


@runtime_checkable
class RAGRerankerPort(Protocol):
    def rerank(self, query: RAGQuery, evidence: Sequence[RAGEvidence]) -> Sequence[RAGEvidence]:
        ...


@runtime_checkable
class RAGContextAssemblerPort(Protocol):
    def assemble(self, query: RAGQuery, evidence: Sequence[RAGEvidence]) -> Sequence[RAGEvidence]:
        ...


__all__ = [
    "RAGChunkStorePort",
    "RAGContextAssemblerPort",
    "RAGRerankerPort",
    "RAGRetrieverPort",
]
