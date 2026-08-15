from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
)
from framework.harness.control_plane.gates import DeterministicGate
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphNodeKind,
    HarnessWaitContract,
    NormalizedHarnessGraph,
)
from framework.harness.graph.runtime_resolution import HarnessGraphRuntimeResolver
from framework.harness.graph.validation.policy import HarnessGraphPreflightPolicy
from framework.harness.graph.validation.registry import validate_registry
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.workers.result import HarnessWorkerResult


def test_resolver_builds_registry_snapshot_from_frozen_graph_and_live_bindings() -> None:
    graph = _graph(
        (_node("collect", gate_refs=("quality@1",)),),
        terminal_policy=_terminal_policy(),
    )
    authority = _authority(
        worker_ids=("collect",),
        gate_registry=_gate_registry(),
        side_effect_registry=_terminal_side_effect_registry(),
    )

    resolved = HarnessGraphRuntimeResolver(authority).resolve(graph)

    assert validate_registry(
        graph,
        resolved.registry_snapshot,
        HarnessGraphPreflightPolicy(),
    ) == ()
    assert resolved.workers_by_node["collect"].reference.exact_ref == "collect@1"
    assert resolved.activities_by_node["collect"].reference.exact_ref == (
        "newsroom.harness-worker-activity@v1"
    )
    assert [
        str(binding.reference) for binding in resolved.gates_by_node["collect"]
    ] == ["quality@1"]
    assert resolved.terminal_side_effect is not None
    references = {
        (reference.contract_kind.value, reference.exact_ref)
        for reference in resolved.registry_snapshot.references
    }
    assert ("worker", "collect@1") in references
    assert ("gate", "quality@1") in references
    assert ("side_effect", "publication.commit@2") in references
    assert ("terminal_policy", "publication@4") in references


def test_resolver_never_registers_control_nodes_as_worker_activities() -> None:
    graph = _graph(
        (
            _node("primary", declaration_order=0),
            _node("fallback", declaration_order=1),
            HarnessControlNode(
                node_id="approval",
                node_kind=HarnessGraphNodeKind.WAIT,
                declaration_order=2,
                wait=HarnessWaitContract(
                    wait_id="approval",
                    kind="approval",
                    correlation={"run": "graph.inputs.run_id"},
                    signal_type="control.approval",
                    signal_version="1",
                    tenant_scope_path="graph.inputs.tenant_id",
                    identity_scope_path="graph.inputs.actor_id",
                ),
            ),
        ),
        entry_node_ids=("primary", "fallback"),
        terminal_node_ids=("approval",),
    )

    resolved = HarnessGraphRuntimeResolver(
        _authority(worker_ids=("primary", "fallback"))
    ).resolve(graph)

    assert set(resolved.workers_by_node) == {"fallback", "primary"}
    assert set(resolved.activities_by_node) == {"fallback", "primary"}
    assert set(resolved.gates_by_node) == {"fallback", "primary"}
    assert "approval" not in resolved.workers_by_node
    assert "approval" not in resolved.activities_by_node


def test_resolver_rejects_missing_worker_before_graph_can_self_authorize() -> None:
    graph = _graph((_node("collect"),))

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRuntimeResolver(_authority(worker_ids=())).resolve(graph)

    assert captured.value.code == "unknown_runtime_contract_binding"
    assert captured.value.details["reference"] == "collect@1"


def test_resolver_uses_checksum_bound_graph_worker_type() -> None:
    graph = _graph((_node("collect", worker_type="llm"),))

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRuntimeResolver(
            _authority(worker_ids=("collect",))
        ).resolve(graph)

    assert captured.value.code == "runtime_worker_type_mismatch"
    assert captured.value.details["expected_worker_type"] == "llm"
    assert captured.value.details["actual_worker_type"] == "script"


def test_resolver_rejects_terminal_policy_without_frozen_snapshot() -> None:
    graph = _graph(
        (_node("collect"),),
        terminal_policy_ref=_ref(
            HarnessContractKind.TERMINAL_POLICY,
            "publication",
            "4",
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRuntimeResolver(
            _authority(worker_ids=("collect",))
        ).resolve(graph)

    assert captured.value.code == "terminal_policy_snapshot_missing"
    assert captured.value.details["reference"] == "publication@4"


def test_resolver_rejects_terminal_gate_not_guaranteed_on_every_path() -> None:
    graph = _graph(
        (
            _node("verified", declaration_order=0, gate_refs=("quality@1",)),
            _node("unchecked", declaration_order=1),
        ),
        entry_node_ids=("verified", "unchecked"),
        terminal_node_ids=("verified", "unchecked"),
        terminal_policy=_terminal_policy(),
    )
    authority = _authority(
        worker_ids=("verified", "unchecked"),
        gate_registry=_gate_registry(),
        side_effect_registry=_terminal_side_effect_registry(),
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRuntimeResolver(authority).resolve(graph)

    assert captured.value.code == "terminal_policy_gate_path_uncovered"
    assert captured.value.details["missing_by_terminal"] == {
        "unchecked": ["quality@1"]
    }


def _graph(
    nodes: tuple[HarnessExecutableNode | HarnessControlNode, ...],
    *,
    entry_node_ids: tuple[str, ...] | None = None,
    terminal_node_ids: tuple[str, ...] | None = None,
    terminal_policy_ref: HarnessContractReference | None = None,
    terminal_policy: HarnessTerminalSideEffectPolicy | None = None,
) -> NormalizedHarnessGraph:
    graph_id = "runtime-resolution"
    if terminal_policy is not None:
        terminal_policy_ref = _ref(
            HarnessContractKind.TERMINAL_POLICY,
            terminal_policy.policy_id,
            terminal_policy.version,
        )
    executable_ids = tuple(
        node.node_id for node in nodes if isinstance(node, HarnessExecutableNode)
    )
    return NormalizedHarnessGraph(
        graph_id=graph_id,
        workflow_id=graph_id,
        workflow_version="1",
        workflow_ref=_ref(HarnessContractKind.WORKFLOW, graph_id, "1"),
        nodes=nodes,
        edges=(),
        entry_node_ids=entry_node_ids or executable_ids[:1],
        terminal_node_ids=terminal_node_ids or executable_ids[-1:],
        terminal_policy_ref=terminal_policy_ref,
        terminal_policy=terminal_policy,
    )


def _node(
    node_id: str,
    *,
    declaration_order: int = 0,
    gate_refs: tuple[str, ...] = (),
    worker_type: str = "script",
) -> HarnessExecutableNode:
    return HarnessExecutableNode(
        node_id=node_id,
        step_id=node_id,
        declaration_order=declaration_order,
        step_ref=_ref(
            HarnessContractKind.STEP,
            f"runtime-resolution:{node_id}",
            "1",
        ),
        worker_ref=_ref(HarnessContractKind.WORKER, node_id, "1"),
        activity_ref=_ref(
            HarnessContractKind.ACTIVITY,
            "newsroom.harness-worker-activity",
            "v1",
        ),
        gate_refs=tuple(_exact_gate_ref(reference) for reference in gate_refs),
        metadata={"worker_type": worker_type},
    )


def _exact_gate_ref(reference: str) -> HarnessContractReference:
    gate_id, version = reference.rsplit("@", maxsplit=1)
    return _ref(HarnessContractKind.GATE, gate_id, version)


def _ref(
    kind: HarnessContractKind,
    contract_id: str,
    version: str,
) -> HarnessContractReference:
    return HarnessContractReference(kind, contract_id, version)


def _terminal_policy() -> HarnessTerminalSideEffectPolicy:
    return HarnessTerminalSideEffectPolicy(
        policy_id="publication",
        version="4",
        handler="publication.commit@2",
        kind="publication",
        requires_approval=False,
        retry_limit=1,
        not_required_evidence_ref="sha256:" + "a" * 64,
        inherited_gate_refs=("quality@1",),
    )


def _authority(
    *,
    worker_ids: tuple[str, ...],
    gate_registry: DeterministicGateRegistry | None = None,
    side_effect_registry: HarnessSideEffectRegistry | None = None,
) -> HarnessRuntimeBindingAuthority:
    return HarnessRuntimeBindingAuthority(
        workers=tuple(
            HarnessWorkerBinding(
                f"{worker_id}@1",
                "script",
                _Worker(worker_id=worker_id),
            )
            for worker_id in worker_ids
        ),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity(),
            ),
        ),
        gate_registry=gate_registry,
        side_effect_registry=side_effect_registry,
    )


def _gate_registry() -> DeterministicGateRegistry:
    gate = _Gate()
    return DeterministicGateRegistry(
        (GateRegistration(GateReference("quality", "1"), gate),)
    )


def _terminal_side_effect_registry() -> HarnessSideEffectRegistry:
    return HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "publication.commit@2",
                "publication",
                _SideEffectHandler(),
                supports_origins=("controller_terminal",),
            ),
        )
    )


@dataclass
class _Worker:
    worker_id: str
    worker_version: str = "1"
    worker_type: str = "script"

    def execute(self, task: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult("succeeded", output=dict(task))


@dataclass
class _Activity:
    activity_contract_id: str = "newsroom.harness-worker-activity"
    activity_contract_version: str = "v1"
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities()

    def dispatch(self, request: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult("succeeded", output=dict(request))


class _Gate(DeterministicGate):
    gate_name = "quality"
    gate_version = "1"


class _SideEffectHandler:
    def commit(self, intent, authorization):
        raise AssertionError("resolution tests must not commit side effects")
