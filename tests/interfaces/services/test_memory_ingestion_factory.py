from __future__ import annotations

from business.layers.output.memory_ingestion import MemoryIngestionService
from interfaces.services.memory_service import memory_ingestion_service_from_env


def test_memory_ingestion_factory_disabled_by_default() -> None:
    assert memory_ingestion_service_from_env(env={}) is None


def test_memory_ingestion_factory_uses_injected_store_when_enabled() -> None:
    store = _CapturingVectorStore()

    service = memory_ingestion_service_from_env(
        env={"NEWS_VECTOR_MEMORY_ENABLED": "1"},
        vector_store=store,
    )

    assert isinstance(service, MemoryIngestionService)
    assert service.vector_store is store
    assert service.memory_runtime is None


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, docs):
        self.documents.extend(docs)
