from __future__ import annotations

from collections import Counter

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


def validate_semantics(graph: NormalizedHarnessGraph) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    nodes_by_id = {node.node_id: node for node in graph.nodes}
    diagnostics.extend(_validate_controls(graph, nodes_by_id))
    diagnostics.extend(_validate_edges(graph))
    diagnostics.extend(_validate_compensations(graph, nodes_by_id))
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
