from __future__ import annotations

import pytest

from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime, MemoryScope
from framework.shared.graph_identity import GraphExecutionIdentity


def _identity() -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id="run-graph",
        graph_id="graph-1",
        graph_version="v1",
        graph_ref="graph-1@v1",
        graph_checksum="sha256:" + "b" * 64,
        node_id="memory-node",
        node_instance_id="memory-instance",
        activity_id="activity-1",
        attempt=1,
    )


def test_graph_scoped_write_requires_exact_execution_identity() -> None:
    with pytest.raises(ValueError, match="exact GraphExecutionIdentity"):
        MemoryRuntime(InMemoryMemoryStore()).write(
            records=[MemoryRecord(content="graph memory", scope=MemoryScope.GRAPH)]
        )


def test_run_only_write_requires_explicit_standalone_and_persists_run_id() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())

    with pytest.raises(ValueError, match="standalone=True"):
        runtime.write(records=[MemoryRecord(content="run memory")], run_id="run-1")

    result = runtime.write(
        records=[MemoryRecord(memory_id="standalone-memory", content="run memory")],
        run_id="run-1",
        standalone=True,
    )

    assert result.success is True
    assert runtime.get("standalone-memory").refs["run_id"] == "run-1"


def test_graph_write_persists_complete_execution_identity_and_trace() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    identity = _identity()

    result = runtime.write(
        records=[
            MemoryRecord(
                memory_id="graph-memory",
                content="graph memory",
                scope=MemoryScope.GRAPH,
            )
        ],
        execution_identity=identity,
    )

    stored = runtime.get("graph-memory")
    assert result.success is True
    assert stored.refs == identity.to_dict()
    assert result.operation_trace.metadata["execution_identity"] == identity.to_dict()


def test_graph_write_rejects_conflicting_record_lineage() -> None:
    identity = _identity()
    conflicting = dict(identity.to_dict())
    conflicting["activity_id"] = "different-activity"

    with pytest.raises(ValueError, match="Graph lineage"):
        MemoryRuntime(InMemoryMemoryStore()).write(
            records=[
                MemoryRecord(
                    content="graph memory",
                    scope=MemoryScope.GRAPH,
                    refs=conflicting,
                )
            ],
            execution_identity=identity,
        )
