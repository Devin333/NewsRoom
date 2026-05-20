from framework.tool import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_memory_tools,
)
from core.framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime
from storage.vector import InMemoryVectorStore, VectorDocument


def test_memory_search_tool_returns_vector_results() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="agent-runtime",
                collection="memories",
                text="Agent runtime workflow execution",
                payload={"topic": "agents"},
                source_type="semantic",
                run_id="run-1",
            ),
            VectorDocument(
                document_id="chip-supply",
                collection="memories",
                text="Semiconductor supply chain update",
                payload={"topic": "chips"},
                source_type="semantic",
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
    assert observation.result.output["collection"] == "memories"
    assert observation.result.output["query"] == "agent runtime workflow"
    assert observation.result.output["result_count"] == 2
    assert observation.result.output["results"][0]["document_id"] == "agent-runtime"
    assert observation.result.output["results"][0]["run_id"] == "run-1"


def test_memory_search_tool_applies_collection_filters_and_threshold() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="ai-record",
                collection="memories",
                text="AI model release memory",
                payload={"topic": "AI"},
                source_type="semantic",
            ),
            VectorDocument(
                document_id="policy-record",
                collection="memories",
                text="Policy consultation memory",
                payload={"topic": "policy"},
                source_type="semantic",
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
                "query": "model memory",
                "collection": "memories",
                "filters": {"topic": "AI"},
                "score_threshold": 0.0,
            },
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["collection"] == "memories"
    assert observation.result.output["filters"] == {"topic": "AI"}
    assert [result["document_id"] for result in observation.result.output["results"]] == [
        "ai-record"
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


def test_memory_recall_tool_uses_memory_runtime_context() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-1",
                    content="Agent memory context is assembled before model calls.",
                    scope="workflow",
                    kind="semantic",
                    refs={"run_id": "run-1"},
                )
            ]
        )
    )
    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=runtime)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.recall",
            arguments={
                "query": "agent memory context",
                "scopes": ["workflow"],
                "limit": 1,
            },
        ),
        ToolPolicy(allowed_tools=["memory.recall"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["result_count"] == 1
    assert observation.result.output["results"][0]["memory_id"] == "mem-1"
    assert "mem-1" in observation.result.output["context_block"]["memory_ids"]


def test_memory_write_tool_requires_side_effect_approval_by_default() -> None:
    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=MemoryRuntime(InMemoryMemoryStore()))
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.write",
            arguments={
                "records": [
                    {
                        "content": "Write through memory runtime.",
                        "scope": "session",
                        "kind": "semantic",
                    }
                ]
            },
        ),
        ToolPolicy(allowed_tools=["memory.write"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED


def test_memory_write_tool_persists_records_when_approved() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=runtime)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.write",
            arguments={
                "run_id": "run-1",
                "records": [
                    {
                        "memory_id": "mem-write",
                        "content": "Memory write persists generic records.",
                        "scope": "session",
                        "kind": "semantic",
                    }
                ],
            },
        ),
        ToolPolicy(
            allowed_tools=["memory.write"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["written_count"] == 1
    assert runtime.get("mem-write").refs["run_id"] == "run-1"


def test_memory_explain_tool_reports_runtime_policy_and_operations() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=runtime)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.explain", arguments={}),
        ToolPolicy(allowed_tools=["memory.explain"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["store_type"] == "InMemoryMemoryStore"
    assert observation.result.output["operations"]["recall"] is True
    assert observation.result.output["operations"]["consolidate"] is True
    assert observation.result.output["tools"]["memory.search"] == "deprecated alias for memory.recall"


def test_memory_consolidate_tool_writes_consolidated_memory_when_approved() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-a",
                    content="Alpha memory.",
                    summary="Alpha",
                    scope="session",
                    kind="semantic",
                    refs={"run_id": "source-run"},
                ),
                MemoryRecord(
                    memory_id="mem-b",
                    content="Beta memory.",
                    summary="Beta",
                    scope="session",
                    kind="semantic",
                    refs={"run_id": "source-run"},
                ),
            ]
        )
    )
    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=runtime)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.consolidate",
            arguments={
                "memory_ids": ["mem-a", "mem-b"],
                "actor": "tool",
                "run_id": "run-1",
                "reason": "stable consolidation",
            },
        ),
        ToolPolicy(
            allowed_tools=["memory.consolidate"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["consolidated_count"] == 1
    consolidated = runtime.get(observation.result.output["memory_ids"][0])
    assert consolidated is not None
    assert consolidated.refs["source_memory_ids"] == ["mem-a", "mem-b"]


def test_memory_forget_tool_deletes_records_when_approved() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-forget",
                    content="Forget me.",
                    scope="session",
                    kind="semantic",
                    refs={"run_id": "run-1"},
                )
            ]
        )
    )
    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=runtime)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="memory.forget",
            arguments={"memory_id": "mem-forget", "reason": "cleanup"},
        ),
        ToolPolicy(
            allowed_tools=["memory.forget"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["forgotten_count"] == 1
    assert runtime.get("mem-forget") is None
