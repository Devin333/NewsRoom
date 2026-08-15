from __future__ import annotations

from collections import Counter, defaultdict, deque

from framework.harness.graph.model import (
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


_NON_FORWARD_EDGE_KINDS = frozenset(
    {
        HarnessGraphEdgeKind.REPAIR,
        HarnessGraphEdgeKind.COMPENSATION,
    }
)


def validate_structure(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    node_ids = [node.node_id for node in graph.nodes]
    edge_ids = [edge.edge_id for edge in graph.edges]
    node_counts = Counter(node_ids)
    edge_counts = Counter(edge_ids)
    unique_node_ids = set(node_ids)

    for node_id in sorted(item for item, count in node_counts.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.STRUCTURAL,
                "duplicate_node_id",
                "graph node identity is not unique",
                node_id=node_id,
                details={"count": node_counts[node_id]},
            )
        )
    for edge_id in sorted(item for item, count in edge_counts.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.STRUCTURAL,
                "duplicate_edge_id",
                "graph edge identity is not unique",
                edge_id=edge_id,
                details={"count": edge_counts[edge_id]},
            )
        )

    for edge in graph.edges:
        if edge.source_id not in unique_node_ids:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "unknown_edge_source",
                    "graph edge source does not resolve",
                    edge_id=edge.edge_id,
                    details={"source_id": edge.source_id},
                )
            )
        if edge.target_id not in unique_node_ids:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "unknown_edge_target",
                    "graph edge target does not resolve",
                    edge_id=edge.edge_id,
                    details={"target_id": edge.target_id},
                )
            )

    for entry_id in graph.entry_node_ids:
        if entry_id not in unique_node_ids:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "unknown_entry_node",
                    "graph entry node does not resolve",
                    node_id=entry_id,
                )
            )
    for terminal_id in graph.terminal_node_ids:
        if terminal_id not in unique_node_ids:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "unknown_terminal_node",
                    "graph terminal node does not resolve",
                    node_id=terminal_id,
                )
            )

    adjacency = _adjacency(graph, include_loop_back=True)
    reachable = _reachable(graph.entry_node_ids, adjacency)
    forward_adjacency = _adjacency(
        graph,
        include_loop_back=True,
        include_auxiliary=False,
    )
    forward_reachable = _reachable(graph.entry_node_ids, forward_adjacency)
    for node_id in sorted(unique_node_ids.difference(reachable)):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.STRUCTURAL,
                "unreachable_node",
                "graph node is unreachable from every entry",
                node_id=node_id,
            )
        )
    for terminal_id in graph.terminal_node_ids:
        if terminal_id in unique_node_ids and terminal_id not in forward_reachable:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "unreachable_terminal",
                    "graph terminal is unreachable from every entry",
                    node_id=terminal_id,
                )
            )

    reverse = _reverse_adjacency(forward_adjacency)
    can_reach_terminal = _reachable(graph.terminal_node_ids, reverse)
    for entry_id in graph.entry_node_ids:
        if entry_id in unique_node_ids and entry_id not in can_reach_terminal:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "entry_without_terminal_path",
                    "graph entry has no path to a terminal",
                    node_id=entry_id,
                )
            )

    forward_outgoing = {
        edge.source_id
        for edge in graph.edges
        if edge.edge_kind not in _NON_FORWARD_EDGE_KINDS
    }
    for terminal_id in graph.terminal_node_ids:
        if terminal_id in forward_outgoing:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "terminal_has_forward_edge",
                    "graph terminal node has a forward outgoing edge",
                    node_id=terminal_id,
                )
            )

    diagnostics.extend(_validate_loop_edges(graph))
    diagnostics.extend(_validate_loop_join_pairs(graph))
    diagnostics.extend(_validate_choice_join_pairs(graph))
    diagnostics.extend(_validate_fork_join_pairs(graph))
    if _contains_undeclared_cycle(graph, unique_node_ids):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.STRUCTURAL,
                "undeclared_graph_cycle",
                "graph contains a cycle outside a declared bounded loop",
            )
        )
    return tuple(diagnostics)


def _validate_loop_edges(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    loop_nodes = {
        node.node_id: node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.node_kind == HarnessGraphNodeKind.LOOP_GUARD
        and node.loop is not None
    }
    for edge in graph.edges:
        if edge.edge_kind not in {
            HarnessGraphEdgeKind.LOOP_BODY,
            HarnessGraphEdgeKind.LOOP_BACK,
            HarnessGraphEdgeKind.LOOP_EXIT,
            HarnessGraphEdgeKind.LOOP_EXHAUSTED,
        }:
            continue
        loop_node = loop_nodes.get(edge.loop_id or "")
        if loop_node is None or loop_node.loop is None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "invalid_loop_edge",
                    "loop edge must reference a declared loop guard",
                    edge_id=edge.edge_id,
                    details={"loop_id": edge.loop_id},
                )
            )
            continue
        loop = loop_node.loop
        valid = False
        code = "invalid_loop_edge"
        message = "loop edge does not match its declared loop contract"
        if edge.edge_kind == HarnessGraphEdgeKind.LOOP_BODY:
            valid = edge.source_id == loop_node.node_id and edge.target_id in set(
                loop.body_entry_node_ids
            )
        elif edge.edge_kind == HarnessGraphEdgeKind.LOOP_BACK:
            code = "invalid_loop_back_edge"
            message = (
                "loop back edge must connect a declared body terminal to its loop guard"
            )
            valid = edge.target_id == loop_node.node_id and edge.source_id in set(
                loop.body_terminal_node_ids
            )
        elif edge.edge_kind == HarnessGraphEdgeKind.LOOP_EXIT:
            valid = edge.source_id == loop_node.node_id and edge.target_id in set(
                loop.exit_node_ids
            )
        elif edge.edge_kind == HarnessGraphEdgeKind.LOOP_EXHAUSTED:
            valid = edge.source_id == loop_node.node_id and edge.target_id in set(
                loop.exhaustion_node_ids
            )
        if not valid:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    code,
                    message,
                    edge_id=edge.edge_id,
                    details={
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "loop_id": edge.loop_id,
                    },
                )
            )
    return tuple(diagnostics)


def _validate_fork_join_pairs(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    controls = {
        node.node_id: node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
    }
    referenced_forks: Counter[str] = Counter()
    for node in controls.values():
        if node.node_kind not in {
            HarnessGraphNodeKind.JOIN_ALL,
            HarnessGraphNodeKind.JOIN_ANY,
        }:
            continue
        if node.join is None:
            continue
        fork = controls.get(node.join.fork_node_id)
        expected_kind = (
            HarnessGraphNodeKind.FORK_ALL
            if node.node_kind == HarnessGraphNodeKind.JOIN_ALL
            else HarnessGraphNodeKind.FORK_ANY
        )
        if fork is None or fork.node_kind != expected_kind:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "fork_join_kind_mismatch",
                    "join does not resolve to the matching fork kind",
                    node_id=node.node_id,
                    details={
                        "fork_node_id": node.join.fork_node_id,
                        "expected_kind": expected_kind.value,
                    },
                )
            )
            continue
        referenced_forks[fork.node_id] += 1
        fork_branches = {branch.branch_id for branch in fork.branches}
        join_branches = set(node.join.required_branch_ids)
        if fork_branches != join_branches:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "fork_join_branch_mismatch",
                    "fork and join branch identities differ",
                    node_id=node.node_id,
                    details={
                        "missing_at_join": sorted(
                            fork_branches.difference(join_branches)
                        ),
                        "unknown_at_join": sorted(
                            join_branches.difference(fork_branches)
                        ),
                    },
                )
            )
    for node in controls.values():
        if node.node_kind not in {
            HarnessGraphNodeKind.FORK_ALL,
            HarnessGraphNodeKind.FORK_ANY,
        }:
            continue
        count = referenced_forks[node.node_id]
        if count != 1:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "fork_join_pair_count_invalid",
                    "parallel fork must have exactly one matching join",
                    node_id=node.node_id,
                    details={"matching_joins": count},
                )
            )
    return tuple(diagnostics)


def _validate_choice_join_pairs(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    controls = {
        node.node_id: node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
    }
    joins_by_choice: Counter[str] = Counter()
    for join in controls.values():
        if join.node_kind is not HarnessGraphNodeKind.CHOICE_JOIN:
            continue
        choice_node_id = join.metadata.get("choice_node_id")
        choice = (
            controls.get(choice_node_id) if isinstance(choice_node_id, str) else None
        )
        if choice is None or choice.node_kind is not HarnessGraphNodeKind.CHOICE:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "choice_join_selector_mismatch",
                    "Choice join does not resolve to a Choice selector",
                    node_id=join.node_id,
                    details={"choice_node_id": choice_node_id},
                )
            )
            continue
        joins_by_choice[choice.node_id] += 1
        if tuple(branch.to_dict() for branch in join.branches) != tuple(
            branch.to_dict() for branch in choice.branches
        ):
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "choice_join_branch_mismatch",
                    "Choice join branch contracts differ from their selector",
                    node_id=join.node_id,
                    details={"choice_node_id": choice.node_id},
                )
            )
        expected_edges = {
            (terminal_id, branch.branch_id)
            for branch in choice.branches
            for terminal_id in branch.terminal_node_ids
        }
        actual_edges = {
            (edge.source_id, edge.branch_id)
            for edge in graph.edges
            if edge.target_id == join.node_id
            and edge.edge_kind is HarnessGraphEdgeKind.DEPENDENCY
        }
        if actual_edges != expected_edges:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "choice_join_edge_mismatch",
                    "Choice join dependencies do not cover its declared branch terminals",
                    node_id=join.node_id,
                    details={
                        "missing": _edge_pair_details(
                            expected_edges.difference(actual_edges)
                        ),
                        "unexpected": _edge_pair_details(
                            actual_edges.difference(expected_edges)
                        ),
                    },
                )
            )
    for choice in controls.values():
        if choice.node_kind is not HarnessGraphNodeKind.CHOICE:
            continue
        if "legacy_source_step_id" in choice.metadata:
            continue
        if joins_by_choice[choice.node_id] != 1:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "choice_join_pair_count_invalid",
                    "explicit Choice must have exactly one deterministic join",
                    node_id=choice.node_id,
                    details={"matching_joins": joins_by_choice[choice.node_id]},
                )
            )
    return tuple(diagnostics)


def _validate_loop_join_pairs(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    controls = {
        node.node_id: node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
    }
    joins_by_loop: Counter[str] = Counter()
    for join in controls.values():
        if join.node_kind is not HarnessGraphNodeKind.LOOP_JOIN:
            continue
        loop_node_id = join.metadata.get("loop_node_id")
        loop = controls.get(loop_node_id) if isinstance(loop_node_id, str) else None
        if (
            loop is None
            or loop.node_kind is not HarnessGraphNodeKind.LOOP_GUARD
            or loop.loop is None
        ):
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "loop_join_selector_mismatch",
                    "Loop join does not resolve to a bounded Loop guard",
                    node_id=join.node_id,
                    details={"loop_node_id": loop_node_id},
                )
            )
            continue
        joins_by_loop[loop.node_id] += 1
        branches = {branch.branch_id: branch for branch in join.branches}
        expected_branch_ids = {"exit"}
        if loop.loop.exhaustion_node_ids:
            expected_branch_ids.add("exhaustion")
        if set(branches) != expected_branch_ids:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "loop_join_branch_mismatch",
                    "Loop join routes differ from the bounded Loop contract",
                    node_id=join.node_id,
                    details={
                        "expected_branch_ids": sorted(expected_branch_ids),
                        "actual_branch_ids": sorted(branches),
                    },
                )
            )
            continue
        if set(branches["exit"].entry_node_ids) != set(loop.loop.exit_node_ids) or (
            "exhaustion" in branches
            and set(branches["exhaustion"].entry_node_ids)
            != set(loop.loop.exhaustion_node_ids)
        ):
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "loop_join_branch_mismatch",
                    "Loop join route entries differ from the bounded Loop contract",
                    node_id=join.node_id,
                )
            )
        expected_edges = {
            (terminal_id, branch.branch_id)
            for branch in branches.values()
            for terminal_id in branch.terminal_node_ids
        }
        actual_edges = {
            (edge.source_id, edge.branch_id)
            for edge in graph.edges
            if edge.target_id == join.node_id
            and edge.edge_kind is HarnessGraphEdgeKind.DEPENDENCY
            and edge.loop_id == loop.node_id
        }
        if actual_edges != expected_edges:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "loop_join_edge_mismatch",
                    "Loop join dependencies do not cover its declared route terminals",
                    node_id=join.node_id,
                    details={
                        "missing": _edge_pair_details(
                            expected_edges.difference(actual_edges)
                        ),
                        "unexpected": _edge_pair_details(
                            actual_edges.difference(expected_edges)
                        ),
                    },
                )
            )
    for loop in controls.values():
        if loop.node_kind is not HarnessGraphNodeKind.LOOP_GUARD:
            continue
        if joins_by_loop[loop.node_id] != 1:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.STRUCTURAL,
                    "loop_join_pair_count_invalid",
                    "bounded Loop must have exactly one deterministic exit join",
                    node_id=loop.node_id,
                    details={"matching_joins": joins_by_loop[loop.node_id]},
                )
            )
    return tuple(diagnostics)


def _edge_pair_details(
    values: set[tuple[str, str | None]],
) -> list[dict[str, str | None]]:
    return [
        {"source_id": source_id, "branch_id": branch_id}
        for source_id, branch_id in sorted(
            values,
            key=lambda item: (item[0], "" if item[1] is None else item[1]),
        )
    ]


def _contains_undeclared_cycle(
    graph: NormalizedHarnessGraph,
    node_ids: set[str],
) -> bool:
    ignored = {HarnessGraphEdgeKind.REPAIR, HarnessGraphEdgeKind.COMPENSATION}
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if (
            edge.edge_kind in ignored
            or (
                edge.edge_kind == HarnessGraphEdgeKind.LOOP_BACK
                and _is_declared_loop_back(graph, edge)
            )
            or edge.source_id not in node_ids
            or edge.target_id not in node_ids
        ):
            continue
        outgoing[edge.source_id].append(edge.target_id)
        indegree[edge.target_id] += 1
    ready = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
    processed = 0
    while ready:
        node_id = ready.popleft()
        processed += 1
        for target_id in sorted(outgoing[node_id]):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
    return processed != len(node_ids)


def _is_declared_loop_back(graph: NormalizedHarnessGraph, edge) -> bool:
    if edge.edge_kind != HarnessGraphEdgeKind.LOOP_BACK or edge.loop_id is None:
        return False
    for node in graph.nodes:
        if (
            isinstance(node, HarnessControlNode)
            and node.node_id == edge.loop_id
            and node.node_kind == HarnessGraphNodeKind.LOOP_GUARD
            and node.loop is not None
        ):
            return (
                edge.target_id == node.node_id
                and edge.source_id in node.loop.body_terminal_node_ids
            )
    return False


def _adjacency(
    graph: NormalizedHarnessGraph,
    *,
    include_loop_back: bool,
    include_auxiliary: bool = True,
) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        values[node.node_id]
    for edge in graph.edges:
        if not include_loop_back and edge.edge_kind == HarnessGraphEdgeKind.LOOP_BACK:
            continue
        if not include_auxiliary and edge.edge_kind in _NON_FORWARD_EDGE_KINDS:
            continue
        if edge.source_id in values:
            values[edge.source_id].append(edge.target_id)
    return {node_id: tuple(sorted(targets)) for node_id, targets in values.items()}


def _reverse_adjacency(
    adjacency: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for node_id in adjacency:
        reverse[node_id]
    for source_id, targets in adjacency.items():
        for target_id in targets:
            if target_id in reverse:
                reverse[target_id].append(source_id)
    return {node_id: tuple(sorted(sources)) for node_id, sources in reverse.items()}


def _reachable(
    start_ids: tuple[str, ...],
    adjacency: dict[str, tuple[str, ...]],
) -> set[str]:
    visited: set[str] = set()
    queue = deque(sorted(node_id for node_id in start_ids if node_id in adjacency))
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        for target_id in adjacency.get(node_id, ()):
            if target_id in adjacency and target_id not in visited:
                queue.append(target_id)
    return visited


__all__ = ["validate_structure"]
