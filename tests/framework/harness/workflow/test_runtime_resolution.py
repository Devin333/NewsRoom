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
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.conditions import ConditionPredicate
from framework.harness.graph.dsl import (
    Choice,
    ChoiceBranch,
    HarnessGraphSpec,
    Sequence,
    StepRef,
    Wait,
)
from framework.harness.graph.model import HarnessControlNode, HarnessExecutableNode
from framework.harness.workflow.runtime_resolution import HarnessGraphRuntimeResolver
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workflow.validation import HarnessGraphPreflight
from framework.harness.workers.result import HarnessWorkerResult


def test_resolver_builds_preflight_snapshot_only_from_live_bindings() -> None:
    workflow = _terminal_workflow()
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    authority = _authority(
        worker_ids=("collect",),
        gate_registry=_gate_registry(),
        side_effect_registry=_terminal_side_effect_registry(),
    )

    resolved = HarnessGraphRuntimeResolver(authority).resolve(workflow, graph)
    prepared = HarnessGraphPreflight().prepare(
        workflow,
        registry=resolved.registry_snapshot,
    )

    assert prepared.is_valid
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
    workflow = HarnessWorkflowSpec(
        workflow_id="control-binding-boundary",
        steps=(
            HarnessStepSpec("primary", "script"),
            HarnessStepSpec("fallback", "script"),
        ),
        entry_step_id="primary",
        graph=HarnessGraphSpec(
            graph_id="control-binding-boundary",
            root=Sequence(
                (
                    Choice(
                        choice_id="route",
                        branches=(
                            ChoiceBranch(
                                "primary",
                                StepRef("primary"),
                                priority=0,
                                condition=ConditionPredicate(
                                    path="graph.inputs.use_primary",
                                    operator="equals",
                                    expected=True,
                                ),
                            ),
                            ChoiceBranch(
                                "fallback",
                                StepRef("fallback"),
                                priority=1,
                                is_default=True,
                            ),
                        ),
                    ),
                    Wait(
                        wait_id="approval",
                        kind="approval",
                        correlation={"run": "graph.inputs.run_id"},
                        signal_type="control.approval",
                        signal_version="1",
                        tenant_scope_path="graph.inputs.tenant_id",
                        identity_scope_path="graph.inputs.actor_id",
                    ),
                )
            ),
            input_keys=("actor_id", "run_id", "tenant_id", "use_primary"),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    resolved = HarnessGraphRuntimeResolver(
        _authority(worker_ids=("primary", "fallback"))
    ).resolve(workflow, graph)
    executable_ids = {
        node.node_id for node in graph.nodes if isinstance(node, HarnessExecutableNode)
    }
    control_ids = {
        node.node_id for node in graph.nodes if isinstance(node, HarnessControlNode)
    }

    assert control_ids == {"approval", "route", "route:join"}
    assert set(resolved.workers_by_node) == executable_ids
    assert set(resolved.activities_by_node) == executable_ids
    assert set(resolved.gates_by_node) == executable_ids
    assert control_ids.isdisjoint(resolved.workers_by_node)
    assert control_ids.isdisjoint(resolved.activities_by_node)


def test_resolver_rejects_missing_worker_before_graph_can_self_authorize() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="missing-worker",
        steps=(HarnessStepSpec("collect", "script"),),
        entry_step_id="collect",
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    authority = _authority(worker_ids=())

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRuntimeResolver(authority).resolve(workflow, graph)

    assert captured.value.code == "unknown_runtime_contract_binding"
    assert captured.value.details["reference"] == "collect@1"


def test_resolver_rejects_terminal_gate_not_guaranteed_on_every_path() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="terminal-gate-paths",
        steps=(
            HarnessStepSpec("verified", "script", quality_gate="quality@1"),
            HarnessStepSpec("unchecked", "script"),
        ),
        entry_step_id="verified",
        graph=HarnessGraphSpec(
            graph_id="terminal-gate-paths",
            root=Choice(
                choice_id="route",
                branches=(
                    ChoiceBranch(
                        "verified",
                        StepRef("verified"),
                        priority=0,
                        condition=ConditionPredicate(
                            path="graph.inputs.use_verified",
                            operator="equals",
                            expected=True,
                        ),
                    ),
                    ChoiceBranch(
                        "unchecked",
                        StepRef("unchecked"),
                        priority=1,
                        is_default=True,
                    ),
                ),
            ),
            input_keys=("use_verified",),
        ),
        terminal_side_effect_policy=_terminal_policy(),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    authority = _authority(
        worker_ids=("verified", "unchecked"),
        gate_registry=_gate_registry(),
        side_effect_registry=_terminal_side_effect_registry(),
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRuntimeResolver(authority).resolve(workflow, graph)

    assert captured.value.code == "terminal_policy_gate_path_uncovered"
    assert captured.value.details["missing_by_terminal"] == {"unchecked": ["quality@1"]}


def _terminal_workflow() -> HarnessWorkflowSpec:
    return HarnessWorkflowSpec(
        workflow_id="terminal-authority",
        steps=(HarnessStepSpec("collect", "script", quality_gate="quality@1"),),
        entry_step_id="collect",
        terminal_side_effect_policy=_terminal_policy(),
    )


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
