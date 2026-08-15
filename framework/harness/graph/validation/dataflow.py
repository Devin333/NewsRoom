from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from typing import Any

from framework.harness.graph.model import (
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdgeKind,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.graph.validation.models import (
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
    produced_after: dict[str, frozenset[str]] = {}
    ancestors_after: dict[str, frozenset[str]] = {}
    graph_inputs = frozenset(graph.input_keys)
    aggregation_inputs = {
        node.merge.aggregation_node_id: str(node.metadata["branch_inputs_key"])
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.merge is not None
        and node.merge.aggregation_node_id is not None
        and isinstance(node.metadata.get("branch_inputs_key"), str)
    }
    while ready:
        node_id = ready.popleft()
        node = nodes_by_id[node_id]
        predecessor_ids = sorted(set(predecessors.get(node_id, ())))
        if predecessor_ids and all(item in available_after for item in predecessor_ids):
            predecessor_values = tuple(available_after[item] for item in predecessor_ids)
            predecessor_produced = tuple(produced_after[item] for item in predecessor_ids)
            if (
                isinstance(node, HarnessControlNode)
                and node.node_kind == HarnessGraphNodeKind.JOIN_ALL
            ):
                available_before = frozenset().union(*predecessor_values)
                produced_before = frozenset().union(*predecessor_produced)
            else:
                available_before = frozenset.intersection(*predecessor_values)
                produced_before = frozenset.intersection(*predecessor_produced)
            ancestors_before = frozenset(predecessor_ids).union(
                *(ancestors_after[item] for item in predecessor_ids)
            )
        else:
            available_before = graph_inputs
            produced_before = frozenset()
            ancestors_before = frozenset()
        produced: frozenset[str] = frozenset()
        if isinstance(node, HarnessExecutableNode):
            synthetic_input = aggregation_inputs.get(node.node_id)
            missing = sorted(
                set(node.input_keys).difference(
                    available_before
                    | ({synthetic_input} if synthetic_input is not None else set())
                )
            )
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
        elif isinstance(node, HarnessControlNode):
            if node.wait is not None:
                diagnostics.extend(
                    _validate_wait_sources(
                        node,
                        graph_inputs=graph_inputs,
                        produced_before=produced_before,
                        ancestors_before=ancestors_before,
                        nodes_by_id=nodes_by_id,
                    )
                )
            if node.merge is not None:
                produced = frozenset(node.merge.output_keys)
        available_after[node_id] = available_before.union(produced)
        produced_after[node_id] = produced_before.union(produced)
        ancestors_after[node_id] = ancestors_before
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


def _validate_wait_sources(
    node: HarnessControlNode,
    *,
    graph_inputs: frozenset[str],
    produced_before: frozenset[str],
    ancestors_before: frozenset[str],
    nodes_by_id: dict[str, HarnessExecutableNode | HarnessControlNode],
) -> tuple[HarnessGraphDiagnostic, ...]:
    if node.wait is None:
        return ()
    sources = {
        node.wait.tenant_scope_path,
        node.wait.identity_scope_path,
        *(
            source
            for source in _nested_string_values(node.wait.correlation)
            if isinstance(source, str)
        ),
    }
    if node.wait.deadline_input_path is not None:
        sources.add(node.wait.deadline_input_path)

    diagnostics: list[HarnessGraphDiagnostic] = []
    for source in sorted(sources):
        if source.startswith("graph.inputs."):
            key = _top_level_key(source, "graph.inputs.")
            if key not in graph_inputs:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "unreachable_wait_input_source",
                        "Wait source does not resolve to a declared graph input",
                        node_id=node.node_id,
                        path=source,
                        details={"input_key": key},
                    )
                )
            continue
        if source.startswith("graph.outputs."):
            key = _top_level_key(source, "graph.outputs.")
            if key not in produced_before:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "unreachable_wait_output_source",
                        "Wait source is not produced on every reachable upstream path",
                        node_id=node.node_id,
                        path=source,
                        details={"output_key": key},
                    )
                )
                continue
            nested_path = _nested_output_path(source, "graph.outputs.")
            producers = tuple(
                producer
                for producer_id, producer in nodes_by_id.items()
                if producer_id in ancestors_before
                and isinstance(producer, HarnessExecutableNode)
                and key in producer.output_keys
            )
            if not any(
                _wait_output_fact_exposed(producer, key, nested_path)
                for producer in producers
            ):
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "unexposed_wait_output_source",
                        "Wait source is outside the producer control-fact contract",
                        node_id=node.node_id,
                        path=source,
                        details={"output_key": key},
                    )
                )
            continue
        if source.startswith("node.outputs."):
            resolved = _resolve_node_output_source(
                source,
                nodes_by_id=nodes_by_id,
            )
            if resolved is None:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "unresolved_wait_node_output_source",
                        "Wait source does not resolve to an exact node output",
                        node_id=node.node_id,
                        path=source,
                    )
                )
                continue
            producer_id, output_key, nested_path = resolved
            if producer_id not in ancestors_before:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "unreachable_wait_node_output_source",
                        "Wait node output source is not an upstream producer",
                        node_id=node.node_id,
                        path=source,
                        details={
                            "producer_node_id": producer_id,
                            "output_key": output_key,
                        },
                    )
                )
            else:
                producer = nodes_by_id[producer_id]
                assert isinstance(producer, HarnessExecutableNode)
                if not _wait_output_fact_exposed(
                    producer,
                    output_key,
                    nested_path,
                ):
                    diagnostics.append(
                        diagnostic(
                            HarnessGraphValidationPhase.DATAFLOW,
                            "unexposed_wait_node_output_source",
                            "Wait node source is outside the producer control-fact contract",
                            node_id=node.node_id,
                            path=source,
                            details={
                                "producer_node_id": producer_id,
                                "output_key": output_key,
                            },
                        )
                    )
    return tuple(diagnostics)


def _nested_string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Mapping):
        return ()
    return tuple(
        source
        for _, child in sorted(value.items(), key=lambda item: str(item[0]))
        for source in _nested_string_values(child)
    )


def _top_level_key(path: str, prefix: str) -> str:
    return path.removeprefix(prefix).split(".", maxsplit=1)[0]


def _nested_output_path(path: str, prefix: str) -> str:
    value = path.removeprefix(prefix)
    _, separator, nested = value.partition(".")
    return nested if separator else ""


def _resolve_node_output_source(
    source: str,
    *,
    nodes_by_id: dict[str, HarnessExecutableNode | HarnessControlNode],
) -> tuple[str, str, str] | None:
    value = source.removeprefix("node.outputs.")
    matches = sorted(
        (
            node_id
            for node_id in nodes_by_id
            if value.startswith(f"{node_id}.")
        ),
        key=lambda node_id: (-len(node_id), node_id),
    )
    if not matches:
        return None
    producer_id = matches[0]
    output_path = value.removeprefix(f"{producer_id}.")
    output_key, separator, nested_path = output_path.partition(".")
    producer = nodes_by_id[producer_id]
    if not isinstance(producer, HarnessExecutableNode) or output_key not in producer.output_keys:
        return None
    return producer_id, output_key, nested_path if separator else ""


def _wait_output_fact_exposed(
    producer: HarnessExecutableNode,
    output_key: str,
    nested_path: str,
) -> bool:
    step_metadata = producer.metadata.get("step_metadata", {})
    if not isinstance(step_metadata, Mapping):
        return False
    raw_paths = step_metadata.get("control_fact_paths", ())
    if isinstance(raw_paths, str) or not isinstance(raw_paths, tuple | list):
        return False
    declared = tuple(str(path).strip() for path in raw_paths if str(path).strip())
    if len(producer.output_keys) > 1:
        relative = tuple(
            "" if path == output_key else path.removeprefix(f"{output_key}.")
            for path in declared
            if path == output_key or path.startswith(f"{output_key}.")
        )
    else:
        relative = declared
    if not relative:
        return False
    if not nested_path:
        return True
    return any(
        path == nested_path or path.startswith(f"{nested_path}.")
        for path in relative
    )


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
    merge_by_join = {
        str(node.metadata["join_node_id"]): node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.merge is not None
        and isinstance(node.metadata.get("join_node_id"), str)
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
        merge = merge_by_join.get(join.node_id)
        if merge is not None and merge.merge is not None:
            expected_branches = set(join.join.required_branch_ids)
            actual_branches = set(merge.merge.input_branch_ids)
            if actual_branches != expected_branches:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "merge_branch_contract_mismatch",
                        "merge inputs do not match the paired Parallel-All branches",
                        node_id=merge.node_id,
                        details={
                            "expected_branch_ids": sorted(expected_branches),
                            "actual_branch_ids": sorted(actual_branches),
                        },
                    )
                )
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
                for output_key in node.output_keys:
                    writes_by_key[output_key].add(branch.branch_id)
        for output_key, branches in sorted(writes_by_key.items()):
            if len(branches) < 2:
                continue
            if merge is not None and merge.merge is not None:
                if output_key in merge.merge.output_keys:
                    continue
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.DATAFLOW,
                        "parallel_shared_write_unmerged",
                        "merge contract does not cover one shared branch output",
                        node_id=merge.node_id,
                        details={
                            "output_key": output_key,
                            "branch_ids": sorted(branches),
                        },
                    )
                )
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
