from backend.layers.memory.ingestion import MemoryIngestionService
from interfaces.services.memory_service import memory_ingestion_service_from_env


def test_memory_ingestion_factory_returns_none_when_enabled_without_sink() -> None:
    service = memory_ingestion_service_from_env(
        env={"NEWS_MEMORY_ENABLED": "true"},
        vector_store=None,
        memory_runtime=None,
    )

    assert service is None


def test_memory_ingestion_factory_wraps_vector_store_as_structured_index() -> None:
    vector_store = _FakeVectorStore()

    service = memory_ingestion_service_from_env(
        env={"NEWS_MEMORY_ENABLED": "true"},
        vector_store=vector_store,
    )

    assert isinstance(service, MemoryIngestionService)
    assert service.vector_store is vector_store
    assert service.vector_index is not None
    assert service.vector_index.__class__.__name__ == "IntelligenceVectorIndexAdapter"


def test_memory_ingestion_factory_does_not_create_postgres_sink_without_dsn() -> None:
    service = memory_ingestion_service_from_env(
        env={
            "NEWS_MEMORY_ENABLED": "true",
            "NEWS_MEMORY_POSTGRES_ENABLED": "true",
        },
        vector_store=None,
        memory_runtime=None,
    )

    assert service is None


class _FakeVectorStore:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, docs):
        self.documents.extend(docs)

    def search(self, query):
        return []

    def get_document(self, collection, document_id):
        return None

    def ensure_collections(self, collections):
        return []
