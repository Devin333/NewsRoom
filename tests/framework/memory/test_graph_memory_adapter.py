from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from framework.memory.integrations.graph import GraphMemoryAdapter
from framework.memory.models import MemoryRecord, MemoryRecallResult
from framework.shared.graph_identity import (
    GraphExecutionIdentity,
    GraphRunIdentity,
    GraphStageIdentity,
)


CHECKSUM = "sha256:" + "a" * 64


def _run_identity() -> GraphRunIdentity:
    return GraphRunIdentity(
        run_id="run-1",
        graph_id="research.graph",
        graph_version="1",
        graph_ref="research.graph@1",
        graph_checksum=CHECKSUM,
    )


def _stage_identity() -> GraphStageIdentity:
    return GraphStageIdentity(
        **_run_identity().to_dict(),
        node_id="collect",
        node_instance_id="node-1",
    )


def _execution_identity() -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        **_stage_identity().to_dict(),
        activity_id="activity-1",
        attempt=1,
    )


@dataclass
class _FakeRuntime:
    recalled: list[Any]

    def recall(self, query: Any, *, policy: Any) -> MemoryRecallResult:
        self.recalled.append((query, policy))
        return MemoryRecallResult(query=query)


def test_graph_memory_adapter_keeps_stage_and_execution_identity_distinct() -> None:
    adapter = GraphMemoryAdapter()
    runtime = _FakeRuntime([])

    adapter.recall_for_stage(
        graph_identity=_stage_identity(),
        query_text="evidence",
        runtime=runtime,
    )
    adapter.recall_for_execution(
        graph_identity=_execution_identity(),
        query_text="evidence",
        runtime=runtime,
    )

    stage_filters = runtime.recalled[0][0].filters
    execution_filters = runtime.recalled[1][0].filters
    assert stage_filters["node_instance_id"] == "node-1"
    assert "activity_id" not in stage_filters
    assert execution_filters["activity_id"] == "activity-1"
    assert execution_filters["attempt"] == 1


def test_graph_memory_adapter_rejects_run_identity_for_physical_memory() -> None:
    adapter = GraphMemoryAdapter()
    runtime = _FakeRuntime([])

    with pytest.raises(TypeError, match="GraphExecutionIdentity"):
        adapter.recall_for_execution(
            graph_identity=_run_identity(),  # type: ignore[arg-type]
            query_text="evidence",
            runtime=runtime,
        )
    with pytest.raises(TypeError, match="GraphStageIdentity"):
        adapter.propose_stage_memory(
            graph_identity=_run_identity(),  # type: ignore[arg-type]
            records=[MemoryRecord(content="stage note")],
        )


def test_graph_memory_adapter_candidates_keep_exact_scope_fields() -> None:
    adapter = GraphMemoryAdapter()

    candidates = adapter.propose_execution_memory(
        graph_identity=_execution_identity(),
        records=[MemoryRecord(content="execution note")],
    )

    assert len(candidates) == 1
    assert candidates[0].metadata["candidate_only"] is True
    assert candidates[0].metadata["activity_id"] == "activity-1"
    assert candidates[0].refs["attempt"] == 1


def test_graph_memory_adapter_has_no_physical_write_surface() -> None:
    adapter = GraphMemoryAdapter()

    assert not hasattr(adapter, "write_execution_memory")
    assert not hasattr(adapter, "write_stage_memory")
    assert not hasattr(adapter, "write_graph_summary")
