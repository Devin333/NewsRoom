from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_memory_tools,
)
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
