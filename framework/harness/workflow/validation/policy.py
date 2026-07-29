from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.graph import (
    HarnessControlNode,
    HarnessGraphEdgeKind,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.validation.models import (
    HarnessGraphDiagnostic,
    HarnessGraphValidationPhase,
    diagnostic,
)


@dataclass(frozen=True, slots=True)
class HarnessGraphPreflightPolicy:
    max_nodes: int = 10_000
    max_edges: int = 50_000
    max_depth: int = 2_048
    max_node_activations: int = 100_000
    max_parallelism: int = 1
    max_active_nodes: int = 1
    max_diagnostics: int = 100

    def __post_init__(self) -> None:
        for field_name in (
            "max_nodes",
            "max_edges",
            "max_depth",
            "max_node_activations",
            "max_parallelism",
            "max_active_nodes",
            "max_diagnostics",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise HarnessValidationError(
                    f"{field_name} must be a positive integer",
                    code="invalid_graph_preflight_policy",
                    details={"field": field_name},
                )


def validate_policy(
    graph: NormalizedHarnessGraph,
    policy: HarnessGraphPreflightPolicy,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    if len(graph.nodes) > policy.max_nodes:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.POLICY,
                "graph_node_limit_exceeded",
                "graph node count exceeds preflight policy",
                details={"actual": len(graph.nodes), "limit": policy.max_nodes},
            )
        )
    if len(graph.edges) > policy.max_edges:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.POLICY,
                "graph_edge_limit_exceeded",
                "graph edge count exceeds preflight policy",
                details={"actual": len(graph.edges), "limit": policy.max_edges},
            )
        )
    depth = _graph_depth(graph)
    if depth > policy.max_depth:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.POLICY,
                "graph_depth_limit_exceeded",
                "graph depth exceeds preflight policy",
                details={"actual": depth, "limit": policy.max_depth},
            )
        )
    activations = _activation_upper_bound(graph)
    if activations > policy.max_node_activations:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.POLICY,
                "graph_activation_limit_exceeded",
                "graph activation upper bound exceeds preflight policy",
                details={"actual": activations, "limit": policy.max_node_activations},
            )
        )
    if policy.max_parallelism > policy.max_active_nodes:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.POLICY,
                "parallelism_exceeds_active_node_limit",
                "physical parallelism cannot exceed active node capacity",
                details={
                    "max_parallelism": policy.max_parallelism,
                    "max_active_nodes": policy.max_active_nodes,
                },
            )
        )
    return tuple(diagnostics)


def _graph_depth(graph: NormalizedHarnessGraph) -> int:
    node_ids = {node.node_id for node in graph.nodes}
    incoming: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    ignored = {
        HarnessGraphEdgeKind.LOOP_BACK,
        HarnessGraphEdgeKind.REPAIR,
        HarnessGraphEdgeKind.COMPENSATION,
    }
    for edge in graph.edges:
        if edge.edge_kind in ignored or edge.source_id not in node_ids or edge.target_id not in node_ids:
            continue
        outgoing[edge.source_id].append(edge.target_id)
        incoming[edge.target_id] += 1
    ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
    depth = {node_id: 1 for node_id in ready}
    processed = 0
    while ready:
        node_id = ready.pop(0)
        processed += 1
        for target_id in sorted(outgoing[node_id]):
            depth[target_id] = max(depth.get(target_id, 1), depth[node_id] + 1)
            incoming[target_id] -= 1
            if incoming[target_id] == 0:
                ready.append(target_id)
                ready.sort()
    if processed != len(node_ids):
        return len(node_ids) + 1
    return max(depth.values(), default=0)


def _activation_upper_bound(graph: NormalizedHarnessGraph) -> int:
    loops = tuple(
        node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.node_kind == HarnessGraphNodeKind.LOOP_GUARD
        and node.loop is not None
        and node.loop.max_iterations > 0
    )
    loop_bodies = {
        node.node_id: _loop_body_node_ids(graph, node)
        for node in loops
    }
    total = 0
    for node in graph.nodes:
        activations = 1
        for loop_node in loops:
            if node.node_id in loop_bodies[loop_node.node_id]:
                activations *= loop_node.loop.max_iterations
        total += activations
    return total


def _loop_body_node_ids(
    graph: NormalizedHarnessGraph,
    loop_node: HarnessControlNode,
) -> frozenset[str]:
    if loop_node.loop is None:
        return frozenset()
    node_ids = {node.node_id for node in graph.nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)
    ignored = {
        HarnessGraphEdgeKind.LOOP_BACK,
        HarnessGraphEdgeKind.REPAIR,
        HarnessGraphEdgeKind.COMPENSATION,
    }
    for edge in graph.edges:
        if (
            edge.edge_kind in ignored
            or edge.source_id not in node_ids
            or edge.target_id not in node_ids
        ):
            continue
        adjacency[edge.source_id].append(edge.target_id)
    visited: set[str] = set()
    queue = deque(sorted(loop_node.loop.body_entry_node_ids))
    while queue:
        node_id = queue.popleft()
        if node_id == loop_node.node_id or node_id not in node_ids or node_id in visited:
            continue
        visited.add(node_id)
        for target_id in sorted(adjacency.get(node_id, ())):
            if target_id not in visited and target_id != loop_node.node_id:
                queue.append(target_id)
    return frozenset(visited)


__all__ = ["HarnessGraphPreflightPolicy", "validate_policy"]
