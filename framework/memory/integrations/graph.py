from __future__ import annotations

from typing import Any

from framework.memory.models import MemoryKind, MemoryQuery, MemoryRecord, MemoryRecallResult, MemoryScope
from framework.memory.policy import DEFAULT_GRAPH_MEMORY_POLICY, MemoryPolicy
from framework.memory.runtime import MemoryRuntime
from framework.shared.graph_identity import (
    GraphExecutionIdentity,
    GraphRunIdentity,
    GraphStageIdentity,
)


GraphMemoryIdentity = GraphRunIdentity | GraphStageIdentity | GraphExecutionIdentity


class GraphMemoryAdapter:
    """Candidate-only Memory integration pinned to an exact Graph scope.

    Run summaries use ``GraphRunIdentity``. Stage-scoped memory uses
    ``GraphStageIdentity`` and activity-scoped memory uses the complete
    ``GraphExecutionIdentity``. A run identity is intentionally rejected for
    execution or stage operations because it cannot identify a physical node.
    """

    def recall_for_execution(
        self,
        *,
        graph_identity: GraphExecutionIdentity,
        query_text: str,
        runtime: MemoryRuntime,
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecallResult:
        _require_identity(graph_identity, GraphExecutionIdentity, "graph_identity")
        return self._recall(
            graph_identity=graph_identity,
            query_text=query_text,
            runtime=runtime,
            policy=policy,
        )

    def recall_for_stage(
        self,
        *,
        graph_identity: GraphStageIdentity,
        query_text: str,
        runtime: MemoryRuntime,
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecallResult:
        _require_identity(graph_identity, GraphStageIdentity, "graph_identity")
        return self._recall(
            graph_identity=graph_identity,
            query_text=query_text,
            runtime=runtime,
            policy=policy,
        )

    def _recall(
        self,
        *,
        graph_identity: GraphMemoryIdentity,
        query_text: str,
        runtime: MemoryRuntime,
        policy: MemoryPolicy | None,
    ) -> MemoryRecallResult:
        effective_policy = policy or DEFAULT_GRAPH_MEMORY_POLICY
        return runtime.recall(
            MemoryQuery(
                query=query_text,
                scopes=[MemoryScope.GRAPH, MemoryScope.SESSION, MemoryScope.GLOBAL],
                kinds=[MemoryKind.CORE, MemoryKind.SEMANTIC, MemoryKind.EPISODIC],
                filters=_identity_fields(graph_identity),
                limit=effective_policy.max_recall_results,
                max_context_tokens=effective_policy.max_context_tokens,
            ),
            policy=effective_policy,
        )

    def propose_execution_memory(
        self,
        *,
        graph_identity: GraphExecutionIdentity,
        records: list[MemoryRecord],
    ) -> tuple[MemoryRecord, ...]:
        _require_identity(graph_identity, GraphExecutionIdentity, "graph_identity")
        return self._prepare_candidates(
            graph_identity=graph_identity,
            records=records,
        )

    def propose_stage_memory(
        self,
        *,
        graph_identity: GraphStageIdentity,
        records: list[MemoryRecord],
    ) -> tuple[MemoryRecord, ...]:
        _require_identity(graph_identity, GraphStageIdentity, "graph_identity")
        return self._prepare_candidates(
            graph_identity=graph_identity,
            records=records,
        )

    def _prepare_candidates(
        self,
        *,
        graph_identity: GraphStageIdentity | GraphExecutionIdentity,
        records: list[MemoryRecord],
    ) -> tuple[MemoryRecord, ...]:
        identity = _identity_fields(graph_identity)
        return tuple(
            record.with_metadata(
                candidate_only=True,
                source="graph_memory_adapter",
                **identity,
            ).with_refs(identity)
            for record in records
        )

    def propose_graph_summary(
        self,
        *,
        graph_identity: GraphRunIdentity,
        summary: str,
    ) -> MemoryRecord:
        _require_identity(graph_identity, GraphRunIdentity, "graph_identity")
        identity = _identity_fields(graph_identity)
        return MemoryRecord(
            kind=MemoryKind.SEMANTIC,
            scope=MemoryScope.GRAPH,
            summary=f"Graph summary for {graph_identity.graph_ref}",
            content=summary,
            metadata={
                "candidate_only": True,
                "source": "graph_memory_adapter",
                **identity,
            },
            refs=identity,
            actor=graph_identity.graph_id,
            namespace="graph.summary",
        )


def _require_identity(
    identity: Any,
    expected_type: type[GraphRunIdentity] | type[GraphStageIdentity] | type[GraphExecutionIdentity],
    field_name: str,
) -> None:
    if not isinstance(identity, expected_type):
        raise TypeError(f"{field_name} must be {expected_type.__name__}")


def _identity_fields(identity: GraphMemoryIdentity) -> dict[str, Any]:
    return {key: value for key, value in identity.to_dict().items() if value is not None}


__all__ = ["GraphMemoryAdapter"]
