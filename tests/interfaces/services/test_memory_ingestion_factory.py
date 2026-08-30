from __future__ import annotations

from backend.layers.memory.ingestion import MemoryIngestionService
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
    assert service.vector_index is not None
    assert service.vector_index.__class__.__name__ == "IntelligenceVectorIndexAdapter"
    assert service.memory_runtime is None


def test_memory_ingestion_factory_does_not_create_sinkless_service() -> None:
    service = memory_ingestion_service_from_env(env={"NEWS_MEMORY_ENABLED": "true"})

    assert service is None


def test_memory_ingestion_factory_uses_runtime_sink_when_enabled() -> None:
    runtime = object()

    service = memory_ingestion_service_from_env(env={"NEWS_MEMORY_ENABLED": "true"}, memory_runtime=runtime)

    assert isinstance(service, MemoryIngestionService)
    assert service.memory_runtime is runtime


def test_memory_ingestion_factory_builds_postgres_repository_when_enabled() -> None:
    service = memory_ingestion_service_from_env(
        env={
            "NEWS_MEMORY_ENABLED": "true",
            "NEWS_MEMORY_POSTGRES_ENABLED": "true",
            "NEWS_DATABASE_DSN": "postgresql://example",
        }
    )

    assert isinstance(service, MemoryIngestionService)
    assert service.repository is not None
    assert service.repository.__class__.__name__ == "PostgresIntelligenceMemoryRepository"


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, docs):
        self.documents.extend(docs)
