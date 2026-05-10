from interfaces.services.memory_service import MemoryApplicationService
from storage.vector import VectorSearchResult


def test_memory_application_service_searches_vector_store() -> None:
    store = _FakeVectorStore()
    service = MemoryApplicationService(vector_store=store)

    result = service.search(
        text="agent runtime",
        collection="report_sections",
        limit=2,
        filters={"topic": "AI"},
    )

    query = store.queries[0]
    assert query.text == "agent runtime"
    assert query.collection == "report_sections"
    assert query.limit == 2
    assert query.filters == {"topic": "AI"}
    assert result.to_dict()["result_count"] == 1
    assert result.to_dict()["results"][0]["document_id"] == "doc-1"


class _FakeVectorStore:
    def __init__(self) -> None:
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [
            VectorSearchResult(
                document_id="doc-1",
                score=0.9,
                text="Agent runtime memory",
                source_type="report_section",
                payload={"document_id": "doc-1"},
            )
        ]
