from storage.vector import DeterministicEmbeddingModel, QdrantVectorStore, VectorDocument, VectorSearchQuery


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


class _FakeQdrantClient:
    def __init__(self, *, points=None) -> None:
        self.points = points or []
        self.created_collections = []
        self.upserts = []
        self.query_calls = []

    def collection_exists(self, collection):
        return False

    def create_collection(self, *, collection_name, vectors_config):
        self.created_collections.append((collection_name, vectors_config))
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
