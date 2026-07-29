from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from typing import Any

from framework.harness.workflow.graph import (
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdgeKind,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.validation.models import (
    HarnessGraphDiagnostic,
    HarnessGraphValidationPhase,
    diagnostic,
)


_NON_DATAFLOW_EDGE_KINDS = frozenset(
    {
        HarnessGraphEdgeKind.LOOP_BACK,
        HarnessGraphEdgeKind.REPAIR,
        HarnessGraphEdgeKind.COMPENSATION,
    }
)


def validate_dataflow(graph: NormalizedHarnessGraph) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    nodes_by_id = {}
    for node in graph.nodes:
        nodes_by_id.setdefault(node.node_id, node)
    predecessors: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in nodes_by_id}
    for edge in graph.edges:
        if (
            edge.edge_kind in _NON_DATAFLOW_EDGE_KINDS
            or edge.source_id not in nodes_by_id
            or edge.target_id not in nodes_by_id
        ):
            continue
        predecessors[edge.target_id].append(edge.source_id)
        outgoing[edge.source_id].append(edge.target_id)
        indegree[edge.target_id] += 1
    ready = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
    available_after: dict[str, frozenset[str]] = {}
    graph_inputs = frozenset(graph.input_keys)
    while ready:
        node_id = ready.popleft()
        node = nodes_by_id[node_id]
        predecessor_ids = sorted(set(predecessors.get(node_id, ())))
        if predecessor_ids and all(item in available_after for item in predecessor_ids):
            available_before = frozenset.intersection(
                *(available_after[item] for item in predecessor_ids)
            )
        else:
            available_before = graph_inputs
        produced: frozenset[str] = frozenset()
        if isinstance(node, HarnessExecutableNode):
            missing = sorted(set(node.input_keys).difference(available_before))
            if missing:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "unreachable_input_producer",
                        "executable node input is not available on every reachable path",
                        node_id=node.node_id,
                        details={"missing_input_keys": missing},
                    )
                )
            produced = frozenset(node.output_keys)
            diagnostics.extend(_validate_shared_output_declaration(node))
        elif isinstance(node, HarnessControlNode) and node.merge is not None:
            produced = frozenset(node.merge.output_keys)
        available_after[node_id] = available_before.union(produced)
        for target_id in sorted(outgoing.get(node_id, ())):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)

    for terminal_id in graph.terminal_node_ids:
        available = available_after.get(terminal_id, graph_inputs)
        missing = sorted(set(graph.terminal_output_keys).difference(available))
        if missing:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.DATAFLOW,
                    "terminal_output_unavailable",
                    "required terminal output is unavailable on this terminal path",
                    node_id=terminal_id,
                    details={"missing_output_keys": missing},
                )
            )

    diagnostics.extend(_validate_parallel_shared_writes(graph, nodes_by_id))
    return tuple(diagnostics)


def _validate_shared_output_declaration(
    node: HarnessExecutableNode,
) -> tuple[HarnessGraphDiagnostic, ...]:
    step_metadata = node.metadata.get("step_metadata", {})
    if not isinstance(step_metadata, Mapping):
        return ()
    shared = _string_sequence(step_metadata.get("shared_output_keys", ()))
    unknown = sorted(set(shared).difference(node.output_keys))
    if not unknown:
        return ()
    return (
        diagnostic(
            HarnessGraphValidationPhase.DATAFLOW,
            "unknown_shared_output_key",
            "shared output declaration does not match executable outputs",
            node_id=node.node_id,
            details={"output_keys": unknown},
        ),
    )


def _validate_parallel_shared_writes(
    graph: NormalizedHarnessGraph,
    nodes_by_id: dict[str, HarnessExecutableNode | HarnessControlNode],
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    join_by_fork = {
        node.join.fork_node_id: node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.join is not None
        and node.node_kind in {HarnessGraphNodeKind.JOIN_ALL, HarnessGraphNodeKind.JOIN_ANY}
    }
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.edge_kind in _NON_DATAFLOW_EDGE_KINDS:
            continue
        adjacency[edge.source_id].append(edge.target_id)
    for fork in graph.nodes:
        if not isinstance(fork, HarnessControlNode) or fork.node_kind not in {
            HarnessGraphNodeKind.FORK_ALL,
            HarnessGraphNodeKind.FORK_ANY,
        }:
            continue
        join = join_by_fork.get(fork.node_id)
        if join is None:
            continue
        writes_by_key: dict[str, set[str]] = defaultdict(set)
        for branch in fork.branches:
            branch_nodes = _nodes_until(
                branch.entry_node_ids,
                stop_id=join.node_id,
                adjacency=adjacency,
            )
            for node_id in branch_nodes:
                node = nodes_by_id.get(node_id)
                if not isinstance(node, HarnessExecutableNode):
                    continue
                step_metadata = node.metadata.get("step_metadata", {})
                if not isinstance(step_metadata, Mapping):
                    continue
                for output_key in _string_sequence(
                    step_metadata.get("shared_output_keys", ())
                ):
                    writes_by_key[output_key].add(branch.branch_id)
        merge_declared = join.join is not None and join.join.merge_ref is not None
        for output_key, branches in sorted(writes_by_key.items()):
            if len(branches) < 2 or merge_declared:
                continue
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.DATAFLOW,
                    "parallel_shared_write_conflict",
                    "parallel branches write one shared key without deterministic merge",
                    node_id=fork.node_id,
                    details={
                        "output_key": output_key,
                        "branch_ids": sorted(branches),
                    },
                )
            )
    return tuple(diagnostics)


def _nodes_until(
    entry_ids: tuple[str, ...],
    *,
    stop_id: str,
    adjacency: dict[str, list[str]],
) -> set[str]:
    visited: set[str] = set()
    queue = deque(sorted(entry_ids))
    while queue:
        node_id = queue.popleft()
        if node_id == stop_id or node_id in visited:
            continue
        visited.add(node_id)
        for target_id in sorted(adjacency.get(node_id, ())):
            if target_id not in visited and target_id != stop_id:
                queue.append(target_id)
    return visited


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(str(item) for item in value)


__all__ = ["validate_dataflow"]
