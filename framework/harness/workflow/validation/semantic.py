from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from framework.harness.workflow.conditions import (
    ConditionAll,
    ConditionAny,
    ConditionPredicate,
    HarnessCondition,
)
from framework.harness.workflow.dsl import WaitKind
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
from framework.harness.workflow.versioning import HARNESS_CONDITION_POLICY_VERSION


_WAIT_SCOPE_PATH_PREFIX = "graph.inputs."
_WAIT_VALUE_PATH_PREFIXES = (
    "graph.inputs.",
    "graph.outputs.",
    "node.outputs.",
)


def validate_semantics(graph: NormalizedHarnessGraph) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    nodes_by_id = {node.node_id: node for node in graph.nodes}
    diagnostics.extend(_validate_controls(graph, nodes_by_id))
    diagnostics.extend(_validate_edges(graph))
    diagnostics.extend(_validate_compensations(graph, nodes_by_id))
    diagnostics.extend(_validate_repair_edges(graph, nodes_by_id))
    return tuple(diagnostics)


def _validate_controls(
    graph: NormalizedHarnessGraph,
    nodes_by_id: dict[str, HarnessExecutableNode | HarnessControlNode],
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    for node in graph.nodes:
        if not isinstance(node, HarnessControlNode):
            continue
        if node.node_kind == HarnessGraphNodeKind.CHOICE:
            diagnostics.extend(_validate_choice(node))
        if node.node_kind in {HarnessGraphNodeKind.FORK_ALL, HarnessGraphNodeKind.FORK_ANY}:
            diagnostics.extend(_validate_parallel_fork(node))
        if node.node_kind == HarnessGraphNodeKind.JOIN_ALL and node.join is not None:
            if node.join.failure_policy not in {"fail_fast", "wait_all", "compensate"}:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.SEMANTIC,
                        "unsupported_parallel_all_failure_policy",
                        "Parallel-All failure policy is unsupported",
                        node_id=node.node_id,
                        details={"failure_policy": node.join.failure_policy},
                    )
                )
        if node.node_kind == HarnessGraphNodeKind.JOIN_ANY and node.join is not None:
            if node.join.failure_policy not in {"fail_all", "compensate"}:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.SEMANTIC,
                        "unsupported_parallel_any_failure_policy",
                        "Parallel-Any failure policy is unsupported",
                        node_id=node.node_id,
                        details={"failure_policy": node.join.failure_policy},
                    )
                )
            if node.join.winner_policy != "first_verified_success_by_stream_sequence":
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.SEMANTIC,
                        "unsupported_parallel_winner_policy",
                        "Parallel-Any winner must use verified durable stream order",
                        node_id=node.node_id,
                    )
                )
        if node.node_kind == HarnessGraphNodeKind.LOOP_GUARD and node.loop is not None:
            if node.loop.max_iterations <= 0:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.SEMANTIC,
                        "invalid_loop_bound",
                        "bounded loop max_iterations must be positive",
                        node_id=node.node_id,
                        details={"max_iterations": node.loop.max_iterations},
                    )
                )
            diagnostics.extend(_validate_condition(node.loop.condition, node_id=node.node_id))
        if node.node_kind == HarnessGraphNodeKind.WAIT and node.wait is not None:
            diagnostics.extend(_validate_wait(node))
            if node.wait.kind == WaitKind.TIMER and node.wait.deadline_input_path is None:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.SEMANTIC,
                        "timer_deadline_missing",
                        "timer Wait requires a persisted deadline input path",
                        node_id=node.node_id,
                    )
                )
            if node.wait.timeout_policy is not None:
                target_id = node.wait.timeout_policy.target_node_id
                if target_id is not None and target_id not in nodes_by_id:
                    diagnostics.append(
                        diagnostic(
                            HarnessGraphValidationPhase.SEMANTIC,
                            "unknown_wait_timeout_target",
                            "Wait timeout route target does not resolve",
                            node_id=node.node_id,
                            details={"target_node_id": target_id},
                        )
                    )
    return tuple(diagnostics)


def _validate_wait(node: HarnessControlNode) -> tuple[HarnessGraphDiagnostic, ...]:
    if node.wait is None:
        return ()
    diagnostics: list[HarnessGraphDiagnostic] = []
    wait = node.wait
    for field_name, path, code in (
        (
            "tenant_scope_path",
            wait.tenant_scope_path,
            "invalid_wait_tenant_scope_path",
        ),
        (
            "identity_scope_path",
            wait.identity_scope_path,
            "invalid_wait_identity_scope_path",
        ),
    ):
        if _is_structural_path(path, (_WAIT_SCOPE_PATH_PREFIX,)):
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                code,
                "Wait authorization scope must come from immutable graph inputs",
                node_id=node.node_id,
                path=path,
                details={"field": field_name},
            )
        )

    for correlation_path, source in _correlation_sources(wait.correlation):
        if _is_structural_path(source, _WAIT_VALUE_PATH_PREFIXES):
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "invalid_wait_correlation_source",
                "Wait correlation must use a restricted structural source path",
                node_id=node.node_id,
                path=correlation_path,
                details={"source": source},
            )
        )

    if wait.deadline_input_path is not None and not _is_structural_path(
        wait.deadline_input_path,
        _WAIT_VALUE_PATH_PREFIXES,
    ):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "invalid_wait_deadline_path",
                "Wait deadline must use a restricted structural source path",
                node_id=node.node_id,
                path=wait.deadline_input_path,
            )
        )
    return tuple(diagnostics)


def _correlation_sources(
    value: object,
    *,
    path: str = "wait.correlation",
) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        items = value.items()
    else:
        return ((path, str(value)),)
    sources: list[tuple[str, str]] = []
    for key, child in sorted(items, key=lambda item: str(item[0])):
        child_path = f"{path}.{key}"
        if isinstance(child, str):
            sources.append((child_path, child))
        elif isinstance(child, Mapping):
            sources.extend(_correlation_sources(child, path=child_path))
        else:
            sources.append((child_path, str(child)))
    return tuple(sources)


def _is_structural_path(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) and len(path) > len(prefix) for prefix in prefixes)


def _validate_choice(node: HarnessControlNode) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    priorities = Counter(branch.priority for branch in node.branches)
    branch_ids = Counter(branch.branch_id for branch in node.branches)
    defaults = [branch for branch in node.branches if branch.is_default]
    for priority in sorted(item for item, count in priorities.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "duplicate_choice_priority",
                "Choice branches must have unique priority",
                node_id=node.node_id,
                details={"priority": priority},
            )
        )
    for branch_id in sorted(item for item, count in branch_ids.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "duplicate_branch_id",
                "Choice branch identity must be unique",
                node_id=node.node_id,
                details={"branch_id": branch_id},
            )
        )
    if len(defaults) > 1:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "multiple_choice_defaults",
                "Choice may declare at most one default branch",
                node_id=node.node_id,
                details={"branch_ids": sorted(branch.branch_id for branch in defaults)},
            )
        )
    for branch in node.branches:
        if branch.is_default and branch.condition is not None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "default_choice_has_condition",
                    "default Choice branch cannot declare a condition",
                    node_id=node.node_id,
                    details={"branch_id": branch.branch_id},
                )
            )
        if not branch.is_default and branch.condition is None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "choice_condition_missing",
                    "non-default Choice branch requires a condition",
                    node_id=node.node_id,
                    details={"branch_id": branch.branch_id},
                )
            )
        if branch.condition is not None:
            diagnostics.extend(_validate_condition(branch.condition, node_id=node.node_id))
    return tuple(diagnostics)


def _validate_parallel_fork(node: HarnessControlNode) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    branch_ids = Counter(branch.branch_id for branch in node.branches)
    namespaces = Counter(branch.output_namespace for branch in node.branches)
    for branch_id in sorted(item for item, count in branch_ids.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "duplicate_branch_id",
                "parallel branch identity must be unique",
                node_id=node.node_id,
                details={"branch_id": branch_id},
            )
        )
    for namespace in sorted(item for item, count in namespaces.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "duplicate_branch_output_namespace",
                "parallel branches must use isolated output namespaces",
                node_id=node.node_id,
                details={"output_namespace": namespace},
            )
        )
    return tuple(diagnostics)


def _validate_edges(graph: NormalizedHarnessGraph) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    for edge in graph.edges:
        if edge.edge_kind == HarnessGraphEdgeKind.CHOICE and edge.condition is None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "choice_edge_condition_missing",
                    "Choice edge requires a condition",
                    edge_id=edge.edge_id,
                )
            )
        if edge.edge_kind == HarnessGraphEdgeKind.DEFAULT and edge.condition is not None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "default_edge_has_condition",
                    "default edge cannot declare a condition",
                    edge_id=edge.edge_id,
                )
            )
        if edge.condition is not None:
            diagnostics.extend(_validate_condition(edge.condition, edge_id=edge.edge_id))
        if edge.edge_kind in {
            HarnessGraphEdgeKind.FORK_BRANCH,
            HarnessGraphEdgeKind.JOIN,
            HarnessGraphEdgeKind.CHOICE,
            HarnessGraphEdgeKind.DEFAULT,
        } and edge.branch_id is None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "edge_branch_identity_missing",
                    "branch edge requires branch identity",
                    edge_id=edge.edge_id,
                )
            )
        if edge.edge_kind in {
            HarnessGraphEdgeKind.LOOP_BODY,
            HarnessGraphEdgeKind.LOOP_BACK,
            HarnessGraphEdgeKind.LOOP_EXIT,
            HarnessGraphEdgeKind.LOOP_EXHAUSTED,
        } and edge.loop_id is None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "edge_loop_identity_missing",
                    "loop edge requires loop identity",
                    edge_id=edge.edge_id,
                )
            )
    return tuple(diagnostics)


def _validate_compensations(
    graph: NormalizedHarnessGraph,
    nodes_by_id: dict[str, HarnessExecutableNode | HarnessControlNode],
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    binding_ids = Counter(reference.binding_id for reference in graph.compensation_refs)
    compensation_edges = tuple(
        edge
        for edge in graph.edges
        if edge.edge_kind == HarnessGraphEdgeKind.COMPENSATION
    )
    for binding_id in sorted(item for item, count in binding_ids.items() if count > 1):
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "duplicate_compensation_binding",
                "compensation binding identity must be unique",
                details={"binding_id": binding_id},
            )
        )
    for reference in graph.compensation_refs:
        origin = nodes_by_id.get(reference.for_node_id)
        compensation = nodes_by_id.get(reference.compensation_node_id)
        if not isinstance(origin, HarnessExecutableNode) or origin.side_effect_ref is None:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "compensation_origin_not_effectful",
                    "compensation origin must be an effectful executable node",
                    node_id=reference.for_node_id,
                    details={"binding_id": reference.binding_id},
                )
            )
        if not isinstance(compensation, HarnessExecutableNode):
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "compensation_node_not_executable",
                    "compensation target must be an executable node",
                    node_id=reference.compensation_node_id,
                    details={"binding_id": reference.binding_id},
                )
            )
        if reference.for_node_id == reference.compensation_node_id:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "cyclic_compensation_binding",
                    "compensation cannot target its originating node",
                    node_id=reference.for_node_id,
                )
            )
        if reference.scope != "node_instance":
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "unsupported_compensation_scope",
                    "compensation binding scope is incompatible",
                    node_id=reference.for_node_id,
                    details={"scope": reference.scope},
                )
            )
        matching_edges = tuple(
            edge
            for edge in compensation_edges
            if edge.source_id == reference.for_node_id
            and edge.target_id == reference.compensation_node_id
        )
        if not matching_edges:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "missing_compensation_edge",
                    "compensation binding requires one exact graph edge",
                    node_id=reference.for_node_id,
                    details={"binding_id": reference.binding_id},
                )
            )
        elif len(matching_edges) > 1:
            diagnostics.append(
                diagnostic(
                    HarnessGraphValidationPhase.SEMANTIC,
                    "duplicate_compensation_edge",
                    "compensation binding resolves to more than one graph edge",
                    node_id=reference.for_node_id,
                    details={"binding_id": reference.binding_id},
                )
            )
    for edge in compensation_edges:
        matches = tuple(
            reference
            for reference in graph.compensation_refs
            if reference.for_node_id == edge.source_id
            and reference.compensation_node_id == edge.target_id
        )
        if matches:
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "unbound_compensation_edge",
                "compensation edge has no exact compensation binding",
                edge_id=edge.edge_id,
            )
        )
    return tuple(diagnostics)


def _validate_repair_edges(
    graph: NormalizedHarnessGraph,
    nodes_by_id: dict[str, HarnessExecutableNode | HarnessControlNode],
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    repair_edges = tuple(
        edge for edge in graph.edges if edge.edge_kind == HarnessGraphEdgeKind.REPAIR
    )
    expected_targets: dict[str, str] = {}
    for node in graph.nodes:
        if not isinstance(node, HarnessExecutableNode):
            continue
        retry_policy = node.metadata.get("retry_policy", {})
        if not isinstance(retry_policy, Mapping):
            continue
        repair_step_id = retry_policy.get("repair_step_id")
        if isinstance(repair_step_id, str) and repair_step_id.strip():
            expected_targets[node.node_id] = repair_step_id.strip()

    for edge in repair_edges:
        expected_step_id = expected_targets.get(edge.source_id)
        target = nodes_by_id.get(edge.target_id)
        if (
            expected_step_id is not None
            and isinstance(target, HarnessExecutableNode)
            and target.step_id == expected_step_id
        ):
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "unbound_repair_edge",
                "repair edge does not match the source node retry policy",
                edge_id=edge.edge_id,
            )
        )

    for source_id, repair_step_id in sorted(expected_targets.items()):
        if any(
            edge.source_id == source_id
            and isinstance(nodes_by_id.get(edge.target_id), HarnessExecutableNode)
            and nodes_by_id[edge.target_id].step_id == repair_step_id
            for edge in repair_edges
        ):
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "missing_repair_edge",
                "retry policy repair target has no exact graph edge",
                node_id=source_id,
                details={"repair_step_id": repair_step_id},
            )
        )
    return tuple(diagnostics)


def _validate_condition(
    condition: HarnessCondition,
    *,
    node_id: str | None = None,
    edge_id: str | None = None,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    if condition.policy_version != HARNESS_CONDITION_POLICY_VERSION:
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.SEMANTIC,
                "unsupported_condition_policy",
                "condition policy version is unsupported",
                node_id=node_id,
                edge_id=edge_id,
                details={"policy_version": condition.policy_version},
            )
        )
    if isinstance(condition, ConditionPredicate):
        return tuple(diagnostics)
    if isinstance(condition, ConditionAll | ConditionAny):
        for child in condition.conditions:
            diagnostics.extend(_validate_condition(child, node_id=node_id, edge_id=edge_id))
    return tuple(diagnostics)


__all__ = ["validate_semantics"]
