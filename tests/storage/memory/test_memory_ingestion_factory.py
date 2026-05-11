from storage.memory import MemoryIngestionService, memory_ingestion_service_from_env


def test_memory_ingestion_factory_disabled_by_default() -> None:
    assert memory_ingestion_service_from_env(env={}) is None


def test_memory_ingestion_factory_uses_injected_store_when_enabled() -> None:
    store = _FakeVectorStore()

    service = memory_ingestion_service_from_env(
        env={"NEWS_VECTOR_MEMORY_ENABLED": "1"},
        vector_store=store,
    )

    assert isinstance(service, MemoryIngestionService)
    assert service.vector_store is store


class _FakeVectorStore:
    def upsert_documents(self, docs):
        return None
