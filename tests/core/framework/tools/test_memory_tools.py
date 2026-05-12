from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_memory_tools,
)
from storage.memory import MemoryIngestionService
from storage.vector import InMemoryVectorStore, VectorDocument


def test_memory_search_tool_returns_vector_results() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="agent-runtime",
                collection="report_sections",
                text="Agent runtime workflow execution",
                payload={"topic": "agents"},
                source_type="report_section",
                run_id="run-1",
            ),
            VectorDocument(
                document_id="chip-supply",
                collection="report_sections",
                text="Semiconductor supply chain update",
                payload={"topic": "chips"},
                source_type="report_section",
                run_id="run-2",
            ),
        ]
    )
    registry = ToolRegistry()
    register_memory_tools(registry, vector_store=store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "agent runtime workflow", "limit": 2},
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["collection"] == "report_sections"
    assert observation.result.output["query"] == "agent runtime workflow"
    assert observation.result.output["result_count"] == 2
    assert observation.result.output["results"][0]["document_id"] == "agent-runtime"
    assert observation.result.output["results"][0]["run_id"] == "run-1"


def test_memory_search_tool_applies_collection_filters_and_threshold() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="ai-evidence",
                collection="evidence_items",
                text="AI model release evidence",
                payload={"topic": "AI"},
                source_type="evidence_item",
                evidence_id="ev-1",
            ),
            VectorDocument(
                document_id="policy-evidence",
                collection="evidence_items",
                text="Policy consultation evidence",
                payload={"topic": "policy"},
                source_type="evidence_item",
                evidence_id="ev-2",
            ),
        ]
    )
    registry = ToolRegistry()
    register_memory_tools(registry, vector_store=store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={
                "query": "model evidence",
                "collection": "evidence_items",
                "filters": {"topic": "AI"},
                "score_threshold": 0.0,
            },
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["collection"] == "evidence_items"
    assert observation.result.output["filters"] == {"topic": "AI"}
    assert [result["document_id"] for result in observation.result.output["results"]] == [
        "ai-evidence"
    ]


def test_memory_search_tool_rejects_blank_query() -> None:
    registry = ToolRegistry()
    register_memory_tools(registry, vector_store=InMemoryVectorStore())
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.search", arguments={"query": "   "}),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "query is required" in (observation.result.error_message or "")


def test_memory_index_tool_indexes_report_and_evidence_through_executor() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        vector_store=store,
        ingestion_service=MemoryIngestionService(store),
    )
    executor = ToolExecutor(registry)

    index_observation = executor.execute(
        ToolCall(
            tool_name="memory.index",
            arguments={
                "run_id": "run-1",
                "report_id": "report-1",
                "topic": "AI",
                "report": {
                    "title": "Daily Intelligence",
                    "sections": [
                        {
                            "title": "Summary",
                            "content": "Agent runtime memory indexing shipped.",
                            "sources": ["https://example.com/source"],
                        }
                    ],
                    "source_urls": ["https://example.com/source"],
                },
                "evidence_bundle": {
                    "bundle_id": "bundle-1",
                    "items": [
                        {
                            "evidence_id": "ev-1",
                            "source_url": "https://example.com/source",
                            "title": "Memory indexing",
                            "summary": "Vector memory indexing now runs through a tool.",
                            "confidence": 0.9,
                            "source_id": "source-1",
                        }
                    ],
                },
            },
        ),
        ToolPolicy(
            allowed_tools=["memory.index"],
            require_approval_for_side_effects=False,
        ),
    )
    search_observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={
                "collection": "report_sections",
                "query": "memory indexing",
            },
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert index_observation.status == ToolStatus.SUCCEEDED
    assert index_observation.result.output["documents_indexed"] == 2
    assert index_observation.result.output["collections"] == [
        "evidence_items",
        "report_sections",
    ]
    assert index_observation.result.output["indexed_inputs"] == [
        "report",
        "evidence_bundle",
    ]
    assert search_observation.status == ToolStatus.SUCCEEDED
    assert search_observation.result.output["result_count"] == 1
    assert search_observation.result.output["results"][0]["report_id"] == "report-1"


def test_memory_index_tool_requires_side_effect_approval_by_default() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        vector_store=store,
        ingestion_service=MemoryIngestionService(store),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.index",
            arguments={
                "run_id": "run-1",
                "report": {
                    "title": "Daily Intelligence",
                    "sections": [{"title": "Summary", "content": "Index me."}],
                },
            },
        ),
        ToolPolicy(allowed_tools=["memory.index"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED


def test_memory_index_tool_rejects_missing_index_payload() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        vector_store=store,
        ingestion_service=MemoryIngestionService(store),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.index", arguments={"run_id": "run-1"}),
        ToolPolicy(
            allowed_tools=["memory.index"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert "report, evidence_bundle, or run_output is required" in (
        observation.result.error_message or ""
    )
