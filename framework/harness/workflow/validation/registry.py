from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.validation.models import (
    HarnessGraphDiagnostic,
    HarnessGraphValidationPhase,
    diagnostic,
)
from framework.harness.workflow.validation.policy import HarnessGraphPreflightPolicy


@dataclass(frozen=True, slots=True)
class HarnessGraphRegistrySnapshot:
    references: tuple[HarnessContractReference, ...]
    parallel_safe_activity_refs: tuple[str, ...] = ()
    parallel_safe_side_effect_refs: tuple[str, ...] = ()
    compensation_safe_activity_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        references = tuple(sorted(self.references))
        if not all(isinstance(item, HarnessContractReference) for item in references):
            raise TypeError("references must contain HarnessContractReference values")
        if len(set(references)) != len(references):
            raise HarnessValidationError(
                "registry snapshot contains duplicate exact references",
                code="duplicate_graph_registry_reference",
            )
        object.__setattr__(self, "references", references)
        object.__setattr__(
            self,
            "parallel_safe_activity_refs",
            _stable_text_tuple(self.parallel_safe_activity_refs),
        )
        object.__setattr__(
            self,
            "parallel_safe_side_effect_refs",
            _stable_text_tuple(self.parallel_safe_side_effect_refs),
        )
        object.__setattr__(
            self,
            "compensation_safe_activity_refs",
            _stable_text_tuple(self.compensation_safe_activity_refs),
        )

    def contains(self, reference: HarnessContractReference) -> bool:
        return reference in self.references

    def to_dict(self) -> dict[str, object]:
        return {
            "references": [reference.to_dict() for reference in self.references],
            "parallel_safe_activity_refs": list(self.parallel_safe_activity_refs),
            "parallel_safe_side_effect_refs": list(
                self.parallel_safe_side_effect_refs
            ),
            "compensation_safe_activity_refs": list(
                self.compensation_safe_activity_refs
            ),
        }


def graph_contract_references(
    graph: NormalizedHarnessGraph,
) -> tuple[HarnessContractReference, ...]:
    references: set[HarnessContractReference] = {graph.workflow_ref}
    if graph.terminal_policy_ref is not None:
        references.add(graph.terminal_policy_ref)
    if graph.terminal_policy is not None:
        policy = graph.terminal_policy
        references.add(
            HarnessContractReference(
                HarnessContractKind.SIDE_EFFECT,
                policy.handler.handler_id,
                policy.handler.version,
            )
        )
        references.update(
            _exact_contract_reference(HarnessContractKind.GATE, reference)
            for reference in policy.inherited_gate_refs
        )
    for node in graph.nodes:
        if isinstance(node, HarnessExecutableNode):
            references.update(
                {
                    node.step_ref,
                    node.worker_ref,
                    node.activity_ref,
                    *node.gate_refs,
                }
            )
            if node.side_effect_ref is not None:
                references.add(node.side_effect_ref)
        elif isinstance(node, HarnessControlNode):
            if node.join is not None and node.join.merge_ref is not None:
                references.add(node.join.merge_ref)
            if node.merge is not None and node.merge.merge_ref is not None:
                references.add(node.merge.merge_ref)
    for compensation in graph.compensation_refs:
        references.add(compensation.handler_ref)
        references.add(compensation.activity_ref)
    return tuple(sorted(references))


def validate_registry(
    graph: NormalizedHarnessGraph,
    registry: HarnessGraphRegistrySnapshot,
    policy: HarnessGraphPreflightPolicy,
) -> tuple[HarnessGraphDiagnostic, ...]:
    diagnostics: list[HarnessGraphDiagnostic] = []
    for reference in graph_contract_references(graph):
        if registry.contains(reference):
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.REGISTRY,
                "unresolved_graph_contract_reference",
                "graph contract reference is not pinned in the registry snapshot",
                details={
                    "contract_kind": reference.contract_kind.value,
                    "reference": reference.exact_ref,
                },
            )
        )

    if policy.max_parallelism > 1:
        safe_activities = set(registry.parallel_safe_activity_refs)
        safe_side_effects = set(registry.parallel_safe_side_effect_refs)
        parallel_node_ids = _parallel_executable_node_ids(graph)
        for node in graph.nodes:
            if (
                not isinstance(node, HarnessExecutableNode)
                or node.node_id not in parallel_node_ids
            ):
                continue
            if node.activity_ref.exact_ref not in safe_activities:
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.REGISTRY,
                        "parallel_activity_safety_unproven",
                        "physical parallel execution lacks exact termination/idempotency/fencing evidence",
                        node_id=node.node_id,
                        details={"activity_ref": node.activity_ref.exact_ref},
                    )
                )
            if (
                node.side_effect_ref is not None
                and node.side_effect_ref.exact_ref not in safe_side_effects
            ):
                diagnostics.append(
                    diagnostic(
                        HarnessGraphValidationPhase.REGISTRY,
                        "parallel_side_effect_safety_unproven",
                        "physical parallel execution lacks a fenced side-effect handler and store",
                        node_id=node.node_id,
                        details={
                            "side_effect_ref": node.side_effect_ref.exact_ref,
                        },
                    )
                )

    compensation_safe = set(registry.compensation_safe_activity_refs)
    for reference in graph.compensation_refs:
        if reference.activity_ref.exact_ref in compensation_safe:
            continue
        diagnostics.append(
            diagnostic(
                HarnessGraphValidationPhase.REGISTRY,
                "compensation_activity_safety_unproven",
                "compensation activity lacks exact idempotency/fencing evidence",
                node_id=reference.compensation_node_id,
                details={"activity_ref": reference.activity_ref.exact_ref},
            )
        )
    return tuple(diagnostics)


def _stable_text_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized_values = tuple(str(item).strip() for item in values)
    if any(not item for item in normalized_values):
        raise HarnessValidationError(
            "registry capability references must be non-blank strings",
            code="invalid_graph_registry_capability",
        )
    return tuple(sorted(set(normalized_values)))


def _exact_contract_reference(
    kind: HarnessContractKind,
    value: str,
) -> HarnessContractReference:
    if not isinstance(value, str) or value.count("@") != 1:
        raise HarnessValidationError(
            "graph runtime reference must use exact '<id>@<version>' form",
            code="graph_inexact_version_reference",
            details={"contract_kind": kind.value, "reference": str(value)},
        )
    contract_id, version = value.rsplit("@", maxsplit=1)
    return HarnessContractReference(kind, contract_id, version)


def _parallel_executable_node_ids(graph: NormalizedHarnessGraph) -> set[str]:
    nodes_by_id = {node.node_id: node for node in graph.nodes}
    joins_by_fork = {
        node.join.fork_node_id: node.node_id
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.join is not None
        and node.node_kind
        in {HarnessGraphNodeKind.JOIN_ALL, HarnessGraphNodeKind.JOIN_ANY}
    }
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.source_id].append(edge.target_id)
    parallel: set[str] = set()
    for node in graph.nodes:
        if not isinstance(node, HarnessControlNode) or node.node_kind not in {
            HarnessGraphNodeKind.FORK_ALL,
            HarnessGraphNodeKind.FORK_ANY,
        }:
            continue
        stop_id = joins_by_fork.get(node.node_id)
        if stop_id is None:
            continue
        queue = deque(
            sorted(
                entry_id
                for branch in node.branches
                for entry_id in branch.entry_node_ids
            )
        )
        visited: set[str] = set()
        while queue:
            node_id = queue.popleft()
            if node_id == stop_id or node_id in visited:
                continue
            visited.add(node_id)
            if isinstance(nodes_by_id.get(node_id), HarnessExecutableNode):
                parallel.add(node_id)
            for target_id in sorted(adjacency.get(node_id, ())):
                if target_id != stop_id and target_id not in visited:
                    queue.append(target_id)
    return parallel


__all__ = [
    "HarnessGraphRegistrySnapshot",
    "graph_contract_references",
    "validate_registry",
]
