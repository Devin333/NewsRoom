from __future__ import annotations

from typing import Protocol

from framework.memory.models import MemoryRecord


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class NoopEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class MemoryEmbeddingIndexer:
    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    def attach_embeddings(self, records: list[MemoryRecord]) -> list[MemoryRecord]:
        embeddings = self.provider.embed_texts([record.content for record in records])
        return [record.with_embedding(embedding) for record, embedding in zip(records, embeddings, strict=False)]
