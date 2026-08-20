from __future__ import annotations

import pytest

from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from framework.tool.builtin.memory import register_memory_tools


def _identity() -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id="run-memory",
        graph_id="research.graph",
        graph_version="1",
        graph_ref="research.graph@1",
        graph_checksum="sha256:" + "a" * 64,
        node_id="recall",
        node_instance_id="recall:1",
        activity_id="activity-memory",
        attempt=1,
    )


class _Runtime:
    def __init__(self) -> None:
        self.queries: list[dict[str, object]] = []

    def recall(self, query: dict[str, object]) -> dict[str, object]:
        self.queries.append(dict(query))
        return {"results": [], "result_count": 0}


def test_memory_tools_require_graph_identity_or_explicit_standalone() -> None:
    with pytest.raises(ValueError, match="GraphExecutionIdentity"):
        register_memory_tools(ToolRegistry(), memory_runtime=_Runtime())

    registry = ToolRegistry()
    register_memory_tools(registry, memory_runtime=_Runtime(), standalone=True)
    assert {tool.name for tool in registry.list_tools()} == {
        "memory.recall",
        "memory.explain",
    }


def test_graph_memory_recall_is_bound_to_exact_identity() -> None:
    runtime = _Runtime()
    identity = _identity()
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        memory_runtime=runtime,
        execution_identity=identity,
    )
    assert registry.require("memory.recall").graph_identity == identity
    executor = ToolExecutor(registry, graph_identity=identity)
    policy = ToolPolicy(allowed_tools=["memory.recall"])

    observation = executor.execute(
        ToolCall(
            tool_name="memory.recall",
            arguments={
                "query": "graph-bound",
                "filters": {"topic": "research"},
            },
        ),
        policy,
    )

    assert observation.status is ToolStatus.SUCCEEDED
    filters = runtime.queries[-1]["filters"]
    assert isinstance(filters, dict)
    assert filters["run_id"] == identity.run_id
    assert filters["graph_checksum"] == identity.graph_checksum
    assert filters["topic"] == "research"

    conflicting = executor.execute(
        ToolCall(
            tool_name="memory.recall",
            arguments={
                "query": "cross-run",
                "filters": {"run_id": "other-run"},
            },
        ),
        policy,
    )
    assert conflicting.status is ToolStatus.FAILED
    assert "conflicts with Graph identity" in (
        conflicting.result.error_message or ""
    )
