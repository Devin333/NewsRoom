from business.layers.output.memory_tools import register_memory_index_tools
from core.framework.tools import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from core.framework.tools.memory_tools import register_memory_tools
from storage.memory import MemoryIngestionService
from storage.vector import InMemoryVectorStore


def test_memory_index_tool_indexes_report_and_evidence_through_executor() -> None:
    store = InMemoryVectorStore()
    registry = ToolRegistry()
    register_memory_tools(registry, vector_store=store)
    register_memory_index_tools(
        registry,
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
    register_memory_index_tools(
        registry,
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
    register_memory_index_tools(
        registry,
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
