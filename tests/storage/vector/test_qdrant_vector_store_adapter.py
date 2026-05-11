from storage.vector import (
    DeterministicEmbeddingModel,
    OpenAICompatibleEmbeddingModel,
    QdrantVectorStore,
    VectorDocument,
    VectorSearchQuery,
    qdrant_store_from_env,
)


def test_qdrant_store_creates_collection_and_upserts_points() -> None:
    client = _FakeQdrantClient()
    store = QdrantVectorStore(
        client,
        embedding_model=DeterministicEmbeddingModel(dimension=8),
        vector_size=8,
    )

    store.upsert_documents(
        [
            VectorDocument(
                document_id="doc-1",
                collection="evidence_items",
                text="Agent runtime evidence",
                payload={"topic": "agents"},
                source_type="evidence_item",
                run_id="run-1",
            )
        ]
    )

    assert client.created_collections[0][0] == "evidence_items"
    assert client.created_collections[0][1].size == 8
    assert client.upserts[0][0] == "evidence_items"
    point = client.upserts[0][1][0]
    assert point.payload["document_id"] == "doc-1"
    assert point.payload["run_id"] == "run-1"
    assert len(point.vector) == 8


def test_qdrant_store_search_translates_filter_and_results() -> None:
    client = _FakeQdrantClient(
        points=[
            _FakePoint(
                score=0.87,
                payload={
                    "document_id": "doc-1",
                    "text": "Agent runtime evidence",
                    "source_type": "evidence_item",
                    "topic": "agents",
                },
            )
        ]
    )
    store = QdrantVectorStore(
        client,
        embedding_model=DeterministicEmbeddingModel(dimension=8),
        vector_size=8,
    )

    results = store.search(
        VectorSearchQuery(
            collection="evidence_items",
            text="agent runtime",
            filters={"topic": "agents"},
            limit=3,
        )
    )

    query_call = client.query_calls[0]
    assert query_call["collection_name"] == "evidence_items"
    assert query_call["query_filter"].must[0].key == "topic"
    assert query_call["query_filter"].must[0].match.value == "agents"
    assert query_call["limit"] == 3
    assert results[0].document_id == "doc-1"
    assert results[0].score == 0.87


def test_qdrant_store_bootstraps_missing_collections_and_reports_existing() -> None:
    client = _FakeQdrantClient(existing_collections={"report_sections"})
    store = QdrantVectorStore(
        client,
        embedding_model=DeterministicEmbeddingModel(dimension=8),
        vector_size=8,
    )

    statuses = store.ensure_collections(["report_sections", "evidence_items"])

    assert [status.to_dict() for status in statuses] == [
        {
            "collection": "report_sections",
            "vector_size": 8,
            "existed_before": True,
            "created": False,
        },
        {
            "collection": "evidence_items",
            "vector_size": 8,
            "existed_before": False,
            "created": True,
        },
    ]
    assert client.created_collections[0][0] == "evidence_items"
    assert client.created_collections[0][1].size == 8


def test_qdrant_store_from_env_uses_configured_dashscope_embeddings(monkeypatch) -> None:
    client = _FakeQdrantClient()
    monkeypatch.setattr("storage.vector.qdrant_store.QdrantClient", lambda url: client)

    store = qdrant_store_from_env(
        env={
            "NEWS_QDRANT_URL": "http://qdrant.example:6333",
            "NEWS_EMBEDDING_PROVIDER": "dashscope",
            "NEWS_EMBEDDING_DIMENSIONS": "128",
        }
    )

    assert store.client is client
    assert store.vector_size == 128
    assert isinstance(store.embedding_model, OpenAICompatibleEmbeddingModel)
    assert store.embedding_model.config.model == "text-embedding-v4"
    assert store.embedding_model.config.api_key_env == "DASHSCOPE_API_KEY"
    assert store.embedding_model.config.request_dimensions == 128


class _FakeQdrantClient:
    def __init__(self, *, points=None, existing_collections=None) -> None:
        self.points = points or []
        self.existing_collections = set(existing_collections or [])
        self.created_collections = []
        self.upserts = []
        self.query_calls = []

    def collection_exists(self, collection):
        return collection in self.existing_collections

    def create_collection(self, *, collection_name, vectors_config):
        self.created_collections.append((collection_name, vectors_config))
        self.existing_collections.add(collection_name)
        return True

    def upsert(self, *, collection_name, points, wait):
        self.upserts.append((collection_name, points, wait))

    def query_points(self, **kwargs):
        self.query_calls.append(kwargs)
        return _FakeQueryResponse(self.points)


class _FakeQueryResponse:
    def __init__(self, points) -> None:
        self.points = points


class _FakePoint:
    def __init__(self, *, score, payload) -> None:
        self.score = score
        self.payload = payload
