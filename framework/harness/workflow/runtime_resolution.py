from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import GateBinding
from framework.harness.side_effects.models import HarnessSideEffectOrigin
from framework.harness.side_effects.registry import HarnessSideEffectHandlerBinding
from framework.harness.workflow.binding_authority import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessCompensationHandlerBinding,
    HarnessDeterministicMergeBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdgeKind,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.validation.registry import HarnessGraphRegistrySnapshot


@dataclass(frozen=True, slots=True)
class HarnessResolvedRuntimeBindings:
    registry_snapshot: HarnessGraphRegistrySnapshot
    workers_by_node: Mapping[str, HarnessWorkerBinding]
    activities_by_node: Mapping[str, HarnessActivityContractBinding]
    gates_by_node: Mapping[str, tuple[GateBinding, ...]]
    side_effects_by_node: Mapping[str, HarnessSideEffectHandlerBinding]
    compensations_by_binding: Mapping[str, HarnessCompensationHandlerBinding]
    merges_by_reference: Mapping[str, HarnessDeterministicMergeBinding]
    terminal_side_effect: HarnessSideEffectHandlerBinding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.registry_snapshot, HarnessGraphRegistrySnapshot):
            raise TypeError("registry_snapshot must be HarnessGraphRegistrySnapshot")
        for field_name in (
            "workers_by_node",
            "activities_by_node",
            "gates_by_node",
            "side_effects_by_node",
            "compensations_by_binding",
            "merges_by_reference",
        ):
            object.__setattr__(
                self,
                field_name,
                _frozen_mapping(getattr(self, field_name)),
            )


class HarnessGraphRuntimeResolver:
    """Resolve compiled Graph references through composition-owned authorities."""

    def __init__(self, authority: HarnessRuntimeBindingAuthority) -> None:
        if not isinstance(authority, HarnessRuntimeBindingAuthority):
            raise TypeError("authority must be HarnessRuntimeBindingAuthority")
        self._authority = authority

    def resolve(
        self,
        workflow: HarnessWorkflowSpec,
        graph: NormalizedHarnessGraph,
        *,
        parallel_activity_capabilities: Mapping[
            str,
            HarnessActivityCapabilities,
        ]
        | None = None,
        fenced_side_effect_store: bool = False,
    ) -> HarnessResolvedRuntimeBindings:
        if not isinstance(workflow, HarnessWorkflowSpec):
            raise TypeError("workflow must be HarnessWorkflowSpec")
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if not isinstance(fenced_side_effect_store, bool):
            raise TypeError("fenced_side_effect_store must be boolean")
        _validate_workflow_reference(workflow, graph)

        steps_by_id = {step.step_id: step for step in workflow.steps}
        references: set[HarnessContractReference] = {graph.workflow_ref}
        workers: dict[str, HarnessWorkerBinding] = {}
        activities: dict[str, HarnessActivityContractBinding] = {}
        gates: dict[str, tuple[GateBinding, ...]] = {}
        side_effects: dict[str, HarnessSideEffectHandlerBinding] = {}
        gate_refs_by_node: dict[str, frozenset[str]] = {}

        for node in graph.nodes:
            if not isinstance(node, HarnessExecutableNode):
                continue
            try:
                step = steps_by_id[node.step_id]
            except KeyError as exc:
                raise _resolution_error(
                    "unknown_graph_step_binding",
                    "compiled executable node does not resolve to a workflow step",
                    node_id=node.node_id,
                    step_id=node.step_id,
                ) from exc
            _validate_step_reference(workflow, step, node)
            references.add(node.step_ref)

            worker = self._authority.resolve_worker(
                node.worker_ref,
                expected_worker_type=step.worker_type,
            )
            activity = self._authority.resolve_activity(node.activity_ref)
            workers[node.node_id] = worker
            activities[node.node_id] = activity
            references.add(worker.reference)
            references.add(activity.reference)

            node_gate_bindings: list[GateBinding] = []
            seen_gate_refs: set[str] = set()
            for gate_ref in node.gate_refs:
                for binding in self._authority.resolve_gate(gate_ref):
                    exact_ref = str(binding.reference)
                    if exact_ref in seen_gate_refs:
                        continue
                    seen_gate_refs.add(exact_ref)
                    node_gate_bindings.append(binding)
                    references.add(_gate_reference(binding))
            gates[node.node_id] = tuple(node_gate_bindings)
            gate_refs_by_node[node.node_id] = frozenset(seen_gate_refs)

            if node.side_effect_ref is not None:
                binding = self._authority.resolve_side_effect(
                    node.side_effect_ref,
                    origin=HarnessSideEffectOrigin.WORKER.value,
                )
                side_effects[node.node_id] = binding
                references.add(_side_effect_reference(binding))

        compensations: dict[str, HarnessCompensationHandlerBinding] = {}
        compensation_safe: set[str] = set()
        for compensation in graph.compensation_refs:
            handler = self._authority.resolve_compensation(compensation.handler_ref)
            activity = self._authority.resolve_activity(
                compensation.activity_ref,
                required_usage="compensation",
            )
            compensations[compensation.binding_id] = handler
            references.add(handler.reference)
            references.add(activity.reference)
            compensation_safe.add(activity.reference.exact_ref)

        merges: dict[str, HarnessDeterministicMergeBinding] = {}
        for reference in _merge_references(graph):
            binding = self._authority.resolve_merge(reference)
            merges[reference.exact_ref] = binding
            references.add(binding.reference)

        terminal_binding, terminal_gate_refs = self._resolve_terminal_policy(
            workflow,
            graph,
            references,
        )
        if terminal_gate_refs:
            _validate_terminal_gate_coverage(
                graph,
                gate_refs_by_node=gate_refs_by_node,
                required_gate_refs=terminal_gate_refs,
            )

        parallel_safe = _parallel_safe_activity_refs(
            activities,
            parallel_activity_capabilities,
        )
        parallel_safe_side_effects = {
            _side_effect_reference(binding).exact_ref
            for binding in side_effects.values()
            if fenced_side_effect_store
            and binding.capabilities.physical_concurrency_safe
        }
        return HarnessResolvedRuntimeBindings(
            registry_snapshot=HarnessGraphRegistrySnapshot(
                references=tuple(references),
                parallel_safe_activity_refs=tuple(parallel_safe),
                parallel_safe_side_effect_refs=tuple(
                    parallel_safe_side_effects
                ),
                compensation_safe_activity_refs=tuple(compensation_safe),
            ),
            workers_by_node=workers,
            activities_by_node=activities,
            gates_by_node=gates,
            side_effects_by_node=side_effects,
            compensations_by_binding=compensations,
            merges_by_reference=merges,
            terminal_side_effect=terminal_binding,
        )

    def _resolve_terminal_policy(
        self,
        workflow: HarnessWorkflowSpec,
        graph: NormalizedHarnessGraph,
        references: set[HarnessContractReference],
    ) -> tuple[HarnessSideEffectHandlerBinding | None, frozenset[str]]:
        policy = workflow.terminal_side_effect_policy
        graph_ref = graph.terminal_policy_ref
        if policy is None:
            if graph_ref is not None:
                raise _resolution_error(
                    "terminal_policy_reference_mismatch",
                    "graph pins a terminal policy absent from the workflow",
                    graph_reference=graph_ref.exact_ref,
                )
            return None, frozenset()
        expected_ref = HarnessContractReference(
            HarnessContractKind.TERMINAL_POLICY,
            policy.policy_id,
            policy.version,
        )
        if graph_ref != expected_ref:
            raise _resolution_error(
                "terminal_policy_reference_mismatch",
                "graph terminal policy reference does not match the workflow policy",
                expected_reference=expected_ref.exact_ref,
                graph_reference=None if graph_ref is None else graph_ref.exact_ref,
            )
        if graph.terminal_policy != policy:
            raise _resolution_error(
                "terminal_policy_snapshot_mismatch",
                "normalized graph terminal policy snapshot does not match the workflow policy",
                reference=expected_ref.exact_ref,
            )
        references.add(expected_ref)
        handler_ref = HarnessContractReference(
            HarnessContractKind.SIDE_EFFECT,
            policy.handler.handler_id,
            policy.handler.version,
        )
        binding = self._authority.resolve_side_effect(
            handler_ref,
            kind=policy.kind,
            origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,
        )
        references.add(_side_effect_reference(binding))
        required_gate_refs: set[str] = set()
        for reference in policy.inherited_gate_refs:
            graph_gate_ref = _exact_reference(HarnessContractKind.GATE, reference)
            resolved = self._authority.resolve_gate(graph_gate_ref)
            for gate_binding in resolved:
                references.add(_gate_reference(gate_binding))
            required_gate_refs.add(graph_gate_ref.exact_ref)
        return binding, frozenset(required_gate_refs)


def _validate_workflow_reference(
    workflow: HarnessWorkflowSpec,
    graph: NormalizedHarnessGraph,
) -> None:
    expected = HarnessContractReference(
        HarnessContractKind.WORKFLOW,
        workflow.workflow_id,
        workflow.workflow_version or "1",
    )
    if graph.workflow_ref != expected:
        raise _resolution_error(
            "workflow_reference_mismatch",
            "compiled graph workflow reference does not match the run workflow",
            expected_reference=expected.exact_ref,
            graph_reference=graph.workflow_ref.exact_ref,
        )


def _validate_step_reference(workflow, step, node: HarnessExecutableNode) -> None:
    expected = HarnessContractReference(
        HarnessContractKind.STEP,
        f"{workflow.workflow_id}:{step.step_id}",
        str(step.metadata.get("step_version", "1")),
    )
    if node.step_ref != expected:
        raise _resolution_error(
            "step_reference_mismatch",
            "compiled node step reference does not match the workflow step",
            node_id=node.node_id,
            expected_reference=expected.exact_ref,
            graph_reference=node.step_ref.exact_ref,
        )


def _merge_references(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessContractReference, ...]:
    references: set[HarnessContractReference] = set()
    for node in graph.nodes:
        if not isinstance(node, HarnessControlNode):
            continue
        if node.join is not None and node.join.merge_ref is not None:
            references.add(node.join.merge_ref)
        if node.merge is not None and node.merge.merge_ref is not None:
            references.add(node.merge.merge_ref)
    return tuple(sorted(references))


def _validate_terminal_gate_coverage(
    graph: NormalizedHarnessGraph,
    *,
    gate_refs_by_node: Mapping[str, frozenset[str]],
    required_gate_refs: frozenset[str],
) -> None:
    node_ids = {node.node_id for node in graph.nodes}
    predecessors: dict[str, list[str]] = defaultdict(list)
    successors: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
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
        predecessors[edge.target_id].append(edge.source_id)
        successors[edge.source_id].append(edge.target_id)
        indegree[edge.target_id] += 1

    guaranteed_after: dict[str, frozenset[str]] = {}
    queue = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
    while queue:
        node_id = queue.popleft()
        incoming = sorted(set(predecessors.get(node_id, ())))
        if incoming and all(item in guaranteed_after for item in incoming):
            guaranteed_before = frozenset.intersection(
                *(guaranteed_after[item] for item in incoming)
            )
        else:
            guaranteed_before = frozenset()
        guaranteed_after[node_id] = guaranteed_before.union(
            gate_refs_by_node.get(node_id, frozenset())
        )
        for successor in sorted(successors.get(node_id, ())):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)

    diagnostic_terminal_ids = tuple(
        sorted(
            {
                leaf_id
                for terminal_id in graph.terminal_node_ids
                for leaf_id in _selection_terminal_leaves(graph, terminal_id)
            }
        )
    )
    missing_by_terminal = {
        terminal_id: sorted(
            required_gate_refs.difference(
                guaranteed_after.get(terminal_id, frozenset())
            )
        )
        for terminal_id in diagnostic_terminal_ids
        if not required_gate_refs.issubset(
            guaranteed_after.get(terminal_id, frozenset())
        )
    }
    if missing_by_terminal:
        raise _resolution_error(
            "terminal_policy_gate_path_uncovered",
            "terminal policy inherited gates are not guaranteed on every terminal path",
            missing_by_terminal=missing_by_terminal,
        )


def _selection_terminal_leaves(
    graph: NormalizedHarnessGraph,
    node_id: str,
    *,
    visited: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    if node_id in visited:
        return (node_id,)
    definition = next((node for node in graph.nodes if node.node_id == node_id), None)
    if not isinstance(definition, HarnessControlNode) or definition.node_kind not in {
        HarnessGraphNodeKind.CHOICE_JOIN,
        HarnessGraphNodeKind.LOOP_JOIN,
    }:
        return (node_id,)
    next_visited = visited.union({node_id})
    return tuple(
        sorted(
            {
                leaf_id
                for branch in definition.branches
                for terminal_id in branch.terminal_node_ids
                for leaf_id in _selection_terminal_leaves(
                    graph,
                    terminal_id,
                    visited=next_visited,
                )
            }
        )
    )


def _gate_reference(binding: GateBinding) -> HarnessContractReference:
    return HarnessContractReference(
        HarnessContractKind.GATE,
        binding.reference.gate_id,
        binding.reference.version,
    )


def _side_effect_reference(
    binding: HarnessSideEffectHandlerBinding,
) -> HarnessContractReference:
    return HarnessContractReference(
        HarnessContractKind.SIDE_EFFECT,
        binding.reference.handler_id,
        binding.reference.version,
    )


def _exact_reference(
    kind: HarnessContractKind,
    value: str,
) -> HarnessContractReference:
    if not isinstance(value, str) or value.count("@") != 1:
        raise _resolution_error(
            "invalid_graph_runtime_reference",
            "runtime reference must use exact '<id>@<version>' form",
            contract_kind=kind.value,
            reference=str(value),
        )
    contract_id, version = value.rsplit("@", maxsplit=1)
    return HarnessContractReference(kind, contract_id, version)


def _frozen_mapping(value: Mapping) -> Mapping:
    if not isinstance(value, Mapping):
        raise TypeError("resolved binding collections must be mappings")
    return MappingProxyType(dict(sorted(value.items(), key=lambda item: str(item[0]))))


def _parallel_safe_activity_refs(
    activities: Mapping[str, HarnessActivityContractBinding],
    dispatcher_capabilities: Mapping[str, HarnessActivityCapabilities] | None,
) -> set[str]:
    if dispatcher_capabilities is None:
        return {
            binding.reference.exact_ref
            for binding in activities.values()
            if binding.capabilities.parallel_safe
        }
    if not isinstance(dispatcher_capabilities, Mapping):
        raise TypeError("parallel_activity_capabilities must be a mapping")

    resolved_refs = {
        binding.reference.exact_ref for binding in activities.values()
    }
    safe_refs: set[str] = set()
    for reference, capabilities in dispatcher_capabilities.items():
        if not isinstance(reference, str) or reference not in resolved_refs:
            raise _resolution_error(
                "unknown_parallel_activity_capability_reference",
                "dispatcher capability evidence references an unresolved activity contract",
                reference=str(reference),
            )
        if not isinstance(capabilities, HarnessActivityCapabilities):
            raise _resolution_error(
                "invalid_parallel_activity_capabilities",
                "dispatcher capability evidence must use HarnessActivityCapabilities",
                reference=reference,
            )
        if capabilities.parallel_safe:
            safe_refs.add(reference)
    return safe_refs


def _resolution_error(
    code: str,
    message: str,
    **details: object,
) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code=code,
        details={"code": code, **details},
    )


__all__ = [
    "HarnessGraphRuntimeResolver",
    "HarnessResolvedRuntimeBindings",
]
