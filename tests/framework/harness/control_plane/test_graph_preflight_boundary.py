from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import HarnessGraphState
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.workflow.binding_authority import HarnessRuntimeBindingAuthority
from framework.harness.workflow.compiler import (
    HarnessGraphCompileResult,
    HarnessWorkflowGraphCompiler,
)
from framework.harness.workflow.dsl import HarnessGraphSpec, StepRef, Wait
from framework.harness.workflow.graph import HarnessGraphEdge
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
)
from framework.harness.workers.result import HarnessWorkerResult


@pytest.mark.parametrize(
    ("case", "expected_phase"),
    (
        ("structural", "structural"),
        ("semantic", "semantic"),
        ("dataflow", "dataflow"),
        ("policy", "policy"),
    ),
)
def test_static_preflight_failure_leaves_no_run_or_partial_graph_state(
    case: str,
    expected_phase: str,
) -> None:
    workflow, graph, policy = _invalid_static_case(case)
    run_id = f"run-invalid-{case}"
    event_port = InMemoryHarnessEventPort()
    worker_calls: list[dict] = []
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "first": lambda task: _record_worker(worker_calls, task),
            "second": lambda task: _record_worker(worker_calls, task),
        },
        graph_preflight=HarnessGraphPreflight(
            compiler=_StaticCompiler(graph),
            policy=policy,
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.initialize(HarnessRunSpec(run_id=run_id, workflow=workflow))

    assert captured.value.code == "harness_graph_preflight_failed"
    assert expected_phase in {
        diagnostic["phase"] for diagnostic in captured.value.details["diagnostics"]
    }
    _assert_preflight_left_no_state(control_plane, event_port, run_id)
    assert worker_calls == []


def test_registry_preflight_failure_leaves_no_run_or_partial_graph_state() -> None:
    workflow = _legacy_workflow()
    run_id = "run-invalid-registry"
    event_port = InMemoryHarnessEventPort()
    control_plane = HarnessControlPlane(
        event_port=event_port,
        runtime_binding_authority=HarnessRuntimeBindingAuthority(),
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.initialize(HarnessRunSpec(run_id=run_id, workflow=workflow))

    assert captured.value.code == "unknown_runtime_contract_binding"
    assert captured.value.details["reference"] == "first@1"
    _assert_preflight_left_no_state(control_plane, event_port, run_id)


def test_invalid_graph_never_invokes_registered_terminal_side_effect() -> None:
    handler = _CountingSideEffectHandler()
    workflow = HarnessWorkflowSpec(
        workflow_id="invalid-side-effect-graph",
        steps=(HarnessStepSpec("first", "script", input_keys=("missing",)),),
        entry_step_id="first",
        graph=HarnessGraphSpec(
            graph_id="invalid-side-effect-graph",
            root=StepRef("first"),
        ),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="publication",
            version="1",
            handler="publication.commit@1",
            kind="publication",
            requires_approval=False,
            retry_limit=1,
            not_required_evidence_ref="sha256:" + "a" * 64,
        ),
    )
    run_id = "run-invalid-side-effect-graph"
    event_port = InMemoryHarnessEventPort()
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "first": lambda task: HarnessWorkerResult("succeeded", output=task)
        },
        side_effect_registry=HarnessSideEffectRegistry(
            (
                HarnessSideEffectHandlerBinding(
                    "publication.commit@1",
                    "publication",
                    handler,
                    supports_origins=("controller_terminal",),
                ),
            )
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.initialize(HarnessRunSpec(run_id=run_id, workflow=workflow))

    assert captured.value.code == "harness_graph_preflight_failed"
    assert handler.calls == 0
    _assert_preflight_left_no_state(control_plane, event_port, run_id)


def test_valid_explicit_graph_initializes_without_legacy_state_or_events() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="explicit-not-active",
        steps=(HarnessStepSpec("first", "script"),),
        entry_step_id="first",
        graph=HarnessGraphSpec(
            graph_id="explicit-not-active",
            root=StepRef("first"),
        ),
    )
    run_id = "run-explicit-not-active"
    event_port = InMemoryHarnessEventPort()
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "first": lambda task: HarnessWorkerResult("succeeded", output=task)
        },
    )

    state = control_plane.initialize(
        HarnessRunSpec(run_id=run_id, workflow=workflow)
    )

    assert isinstance(state, HarnessGraphState)
    assert state.graph_ref.checksum == control_plane._prepared_graphs[run_id].checksum
    assert event_port.events == []
    assert event_port.created_activities == []
    assert control_plane.graph_transition_port.recover_graph(run_id).state == state


def test_failed_preflight_does_not_poison_same_run_id_for_corrected_spec() -> None:
    workflow = _legacy_workflow()
    valid_graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    invalid_graph = replace(
        valid_graph,
        edges=(
            HarnessGraphEdge(
                edge_id="missing-source",
                source_id="missing",
                target_id="first",
                edge_kind="dependency",
            ),
        ),
        checksum=None,
    )
    compiler = _SwitchingCompiler(invalid_graph)
    run_id = "run-preflight-retry"
    event_port = InMemoryHarnessEventPort()
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "first": lambda task: HarnessWorkerResult("succeeded", output=task),
            "second": lambda task: HarnessWorkerResult("succeeded", output=task),
        },
        graph_preflight=HarnessGraphPreflight(compiler=compiler),
    )
    run_spec = HarnessRunSpec(run_id=run_id, workflow=workflow)

    with pytest.raises(HarnessValidationError):
        control_plane.initialize(run_spec)
    _assert_preflight_left_no_state(control_plane, event_port, run_id)

    state = control_plane.initialize(run_spec)

    assert state.run_id == run_id
    assert run_id in control_plane._prepared_run_specs
    assert run_id in control_plane._prepared_graphs
    assert event_port.events == []
    assert control_plane.graph_transition_port.recover_graph(run_id).state == state


def _invalid_static_case(
    case: str,
) -> tuple[HarnessWorkflowSpec, object, HarnessGraphPreflightPolicy]:
    workflow = _legacy_workflow()
    compiler = HarnessWorkflowGraphCompiler()
    valid_graph = compiler.compile(workflow).graph
    if case == "structural":
        graph = replace(
            valid_graph,
            edges=(
                HarnessGraphEdge(
                    edge_id="missing-source",
                    source_id="missing",
                    target_id="first",
                    edge_kind="dependency",
                ),
            ),
            checksum=None,
        )
        return workflow, graph, HarnessGraphPreflightPolicy()
    if case == "semantic":
        semantic_workflow = HarnessWorkflowSpec(
            workflow_id="invalid-wait",
            steps=(HarnessStepSpec("first", "script"),),
            entry_step_id="first",
            graph=HarnessGraphSpec(
                graph_id="invalid-wait",
                root=Wait(
                    wait_id="approval",
                    kind="approval",
                    correlation={"subject": "graph.inputs..subject"},
                    signal_type="approval",
                    signal_version="1",
                    tenant_scope_path="graph.inputs.tenant_id",
                    identity_scope_path="graph.inputs.actor_id",
                ),
                input_keys=("tenant_id", "actor_id", "subject"),
            ),
        )
        return (
            semantic_workflow,
            compiler.compile(semantic_workflow).graph,
            HarnessGraphPreflightPolicy(),
        )
    if case == "dataflow":
        dataflow_workflow = HarnessWorkflowSpec(
            workflow_id="missing-input",
            steps=(HarnessStepSpec("first", "script", input_keys=("missing",)),),
            entry_step_id="first",
            graph=HarnessGraphSpec(
                graph_id="missing-input",
                root=StepRef("first"),
            ),
        )
        return (
            dataflow_workflow,
            compiler.compile(dataflow_workflow).graph,
            HarnessGraphPreflightPolicy(),
        )
    if case == "policy":
        return workflow, valid_graph, HarnessGraphPreflightPolicy(max_nodes=1)
    raise AssertionError(f"unsupported case: {case}")


def _legacy_workflow() -> HarnessWorkflowSpec:
    return HarnessWorkflowSpec(
        workflow_id="preflight-boundary",
        steps=(
            HarnessStepSpec("first", "script"),
            HarnessStepSpec("second", "script"),
        ),
        entry_step_id="first",
    )


def _record_worker(calls: list[dict], task: dict) -> HarnessWorkerResult:
    calls.append(task)
    return HarnessWorkerResult("succeeded", output=task)


def _assert_preflight_left_no_state(
    control_plane: HarnessControlPlane,
    event_port: InMemoryHarnessEventPort,
    run_id: str,
) -> None:
    assert event_port.events == []
    assert event_port.created_activities == []
    for cache_name in (
        "_prepared_run_specs",
        "_prepared_graphs",
        "_resolved_graph_bindings",
        "_worker_bindings_by_run",
        "_activity_contract_versions_by_run",
        "_gate_bindings_by_run",
        "_side_effect_bindings_by_run",
        "_terminal_side_effect_bindings",
    ):
        assert run_id not in getattr(control_plane, cache_name)
    if control_plane.graph_transition_port is not None:
        recovery = control_plane.graph_transition_port.recover_graph(run_id)
        assert recovery.graph is None
        assert recovery.run_spec_checksum is None
        assert recovery.state is None
        assert recovery.expected_last_sequence == 0
        assert recovery.decision_commits == ()
        assert recovery.projection_commits == ()
        assert recovery.activity_result_commits == ()
        assert recovery.observation_commits == ()
        assert recovery.activities == ()


class _StaticCompiler:
    def __init__(self, graph) -> None:
        self.graph = graph

    def compile(self, workflow) -> HarnessGraphCompileResult:
        return HarnessGraphCompileResult(
            graph=self.graph,
            declaration_mode=workflow.declaration_mode,
        )


class _SwitchingCompiler:
    def __init__(self, invalid_graph) -> None:
        self.invalid_graph = invalid_graph
        self.calls = 0
        self.delegate = HarnessWorkflowGraphCompiler()

    def compile(self, workflow) -> HarnessGraphCompileResult:
        self.calls += 1
        if self.calls == 1:
            return HarnessGraphCompileResult(
                graph=self.invalid_graph,
                declaration_mode=workflow.declaration_mode,
            )
        return self.delegate.compile(workflow)


class _CountingSideEffectHandler:
    def __init__(self) -> None:
        self.calls = 0

    def commit(self, intent, authorization):
        self.calls += 1
        raise AssertionError("invalid graph must never invoke a side effect")
