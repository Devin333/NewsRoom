from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_qdrant_tools,
)
from storage.vector import InMemoryVectorStore, VectorDocument, VectorSearchResult


def test_qdrant_search_tool_returns_vector_collection_results() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="agent-runtime",
                collection="runtime_records",
                text="Agent runtime workflow execution",
                payload={"topic": "agents"},
                source_type="runtime_record",
                run_id="run-1",
            ),
            VectorDocument(
                document_id="chip-supply",
                collection="runtime_records",
                text="Semiconductor supply chain update",
                payload={"topic": "chips"},
                source_type="runtime_record",
                run_id="run-2",
            ),
        ]
    )
    registry = ToolRegistry()
    register_qdrant_tools(registry, vector_store=store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="qdrant.search",
            arguments={
                "collection": "runtime_records",
                "query": "agent runtime workflow",
                "limit": 2,
            },
        ),
        ToolPolicy(allowed_tools=["qdrant.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["collection"] == "runtime_records"
    assert observation.result.output["query"] == "agent runtime workflow"
    assert observation.result.output["result_count"] == 2
    assert observation.result.output["results"][0]["document_id"] == "agent-runtime"
    assert observation.result.output["results"][0]["run_id"] == "run-1"


def test_qdrant_search_tool_passes_vector_filters_and_threshold() -> None:
    store = _RecordingSearchStore()
    registry = ToolRegistry()
    register_qdrant_tools(registry, vector_store=store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="qdrant.search",
            arguments={
                "collection": "runtime_records",
                "vector": [0.2, 0.8],
                "filters": {"topic": "AI"},
                "limit": 500,
                "score_threshold": 0.7,
            },
        ),
        ToolPolicy(allowed_tools=["qdrant.search"]),
    )

    query = store.queries[0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert query.collection == "runtime_records"
    assert query.text == ""
    assert query.vector == [0.2, 0.8]
    assert query.filters == {"topic": "AI"}
    assert query.limit == 100
    assert query.score_threshold == 0.7
    assert observation.result.output["query"] is None
    assert observation.result.output["vector_dimensions"] == 2
    assert observation.result.output["results"][0]["document_id"] == "doc-1"


def test_qdrant_search_tool_rejects_missing_query_and_vector() -> None:
    registry = ToolRegistry()
    register_qdrant_tools(registry, vector_store=InMemoryVectorStore())
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="qdrant.search",
            arguments={"collection": "runtime_records", "query": "   "},
        ),
        ToolPolicy(allowed_tools=["qdrant.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "query or vector is required" in (observation.result.error_message or "")


def test_qdrant_upsert_tool_writes_searchable_documents_through_executor() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_qdrant_tools(registry, vector_store=store, document_store=store)
    executor = ToolExecutor(registry)

    upsert_observation = executor.execute(
        ToolCall(
            tool_name="qdrant.upsert",
            arguments={
                "collection": "runtime_records",
                "documents": [
                    {
                        "document_id": "doc-1",
                        "text": "AI model release record",
                        "source_type": "runtime_record",
                        "payload": {"topic": "AI"},
                        "run_id": "run-1",
                        "refs": {"reference_id": "ref-1"},
                    }
                ],
            },
        ),
        ToolPolicy(
            allowed_tools=["qdrant.upsert"],
            require_approval_for_side_effects=False,
        ),
    )
    search_observation = executor.execute(
        ToolCall(
            tool_name="qdrant.search",
            arguments={
                "collection": "runtime_records",
                "query": "model release",
                "filters": {"topic": "AI"},
            },
        ),
        ToolPolicy(allowed_tools=["qdrant.search"]),
    )

    assert upsert_observation.status == ToolStatus.SUCCEEDED
    assert upsert_observation.result.output == {
        "documents_upserted": 1,
        "collections": ["runtime_records"],
        "document_ids": ["doc-1"],
    }
    assert search_observation.status == ToolStatus.SUCCEEDED
    assert search_observation.result.output["result_count"] == 1
    assert search_observation.result.output["results"][0]["document_id"] == "doc-1"
    assert search_observation.result.output["results"][0]["run_id"] == "run-1"
    assert search_observation.result.output["results"][0]["refs"]["reference_id"] == "ref-1"


def test_qdrant_upsert_tool_requires_side_effect_approval_by_default() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_qdrant_tools(registry, vector_store=store, document_store=store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="qdrant.upsert",
            arguments={
                "collection": "runtime_records",
                "documents": [
                    {
                        "document_id": "doc-1",
                        "text": "AI model release record",
                        "source_type": "runtime_record",
                    }
                ],
            },
        ),
        ToolPolicy(allowed_tools=["qdrant.upsert"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED


def test_qdrant_upsert_tool_rejects_documents_without_collection() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_qdrant_tools(registry, vector_store=store, document_store=store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="qdrant.upsert",
            arguments={
                "documents": [
                    {
                        "document_id": "doc-1",
                        "text": "AI model release record",
                        "source_type": "runtime_record",
                    }
                ],
            },
        ),
        ToolPolicy(
            allowed_tools=["qdrant.upsert"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert "document collection is required" in (observation.result.error_message or "")


class _RecordingSearchStore:
    def __init__(self) -> None:
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [
            VectorSearchResult(
                document_id="doc-1",
                score=0.91,
                text="AI model release record",
                source_type="runtime_record",
                payload={
                    "document_id": "doc-1",
                    "topic": "AI",
                    "refs": {"reference_id": "ref-1"},
                },
            )
        ]
