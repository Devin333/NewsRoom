from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.events.errors import EventReplayMismatchError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.graph_checkpoint import (
    HarnessGraphCheckpoint,
    HarnessGraphCheckpointReader,
    HarnessGraphHistoryReducer,
    HarnessPinnedDecisionKernel,
    graph_history_evidence_ref,
    quarantine_graph_replay_failure,
)
from framework.harness.control_plane.graph_decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphDecisionCommit,
    InMemoryHarnessGraphTransitionPort,
)
from framework.harness.control_plane.scheduler import (
    HarnessGraphStepSchedulingInput,
    HarnessScheduler,
)
from framework.harness.control_plane.graph_state import (
    HarnessGraphReference,
    HarnessGraphState,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.control_plane.step_lifecycle import (
    StepLifecycleBudget,
    StepLifecycleObservations,
)
from framework.harness.control_plane.transition import run_spec_checksum
from framework.harness.graph import (
    GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA,
    GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA,
    GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_GRAPH_CHECKPOINT_SCHEMA,
    HARNESS_GRAPH_DECISION_SCHEMA,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    HARNESS_GRAPH_STATE_SCHEMA,
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphCompiler,
    HarnessGraphDefinition,
    HarnessGraphLeafBinding,
    HarnessGraphSpec,
    HarnessLeafActivityKind,
    HarnessStepSpec,
    HarnessWorkerType,
    NormalizedHarnessGraph,
    StepRef,
)
from framework.harness.graph.validation import HarnessGraphPreflightPolicy
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.workflow.spec import HarnessWorkflowSpec


_NOW = datetime(2026, 8, 17, tzinfo=UTC)


def test_graph_only_crash_recovery_and_checkpoint_replay_are_self_contained() -> None:
    step, graph = _compiled_graph()
    run_spec = _run_spec("graph-only-recovery", step)
    spec_checksum = run_spec_checksum(run_spec)
    port = InMemoryHarnessGraphTransitionPort()
    runtime = HarnessGraphControlPlaneRuntime(port)
    initial = runtime.initialize(
        run_spec,
        graph,
        HarnessGraphPreflightPolicy(),
        run_spec_checksum=spec_checksum,
    )
    scheduler = HarnessScheduler()
    activation = scheduler.next_decision(initial, graph=graph)

    assert activation is not None
    assert activation.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
    assert activation.schema_version == GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA
    port.commit_graph_decision(
        activation,
        occurred_at=_NOW,
        expected_last_sequence=initial.last_event_sequence,
    )

    recovered = HarnessGraphControlPlaneRuntime(port).recover(
        run_spec.run_id,
        graph,
        run_spec_checksum=spec_checksum,
    )
    recovery = port.recover_graph(run_spec.run_id)
    checkpoint = HarnessGraphCheckpoint.from_state(
        "graph-only-initial",
        initial,
        created_at=_NOW,
        history_evidence_ref=graph_history_evidence_ref(
            recovery,
            through_sequence=initial.last_event_sequence,
            projection_checksum=initial.projection_checksum,
        ),
    )
    kernel = HarnessPinnedDecisionKernel(
        graph,
        lambda state, _commit: scheduler.next_decision(state, graph=graph),
    )
    replayed = HarnessGraphHistoryReducer().rebuild(
        recovery,
        checkpoint=checkpoint,
        verify_history=True,
        decision_kernel=kernel,
    )
    checkpoint_payload = checkpoint.to_dict()

    assert recovered == recovery.state == replayed.state
    assert recovered.last_event_sequence == 3
    assert len(recovered.node_instances) == 1
    assert kernel.compiler_version == HARNESS_GRAPH_ONLY_COMPILER_VERSION
    assert checkpoint.schema_version == GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA
    assert checkpoint.state.schema_version == GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA
    assert checkpoint.graph_ref.schema_version == (
        GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
    )
    assert checkpoint.graph_ref.graph_ref == graph.graph_ref
    assert "workflow_ref" not in _mapping_keys(checkpoint_payload)
    assert HarnessGraphCheckpointReader().read(checkpoint_payload) == checkpoint
    with pytest.raises(HarnessValidationError) as state_schema:
        replace(initial, schema_version=HARNESS_GRAPH_STATE_SCHEMA)
    with pytest.raises(HarnessValidationError) as checkpoint_schema:
        replace(checkpoint, schema_version=HARNESS_GRAPH_CHECKPOINT_SCHEMA)

    assert state_schema.value.code == "graph_state_schema_mismatch"
    assert checkpoint_schema.value.code == "graph_checkpoint_schema_mismatch"


def test_graph_only_replay_rejects_a_changed_gate_version_without_worker_calls() -> None:
    step, graph = _compiled_graph(gate_ref="AnalysisGate@1")
    _, changed_graph = _compiled_graph(gate_ref="AnalysisGate@2")
    run_spec = _run_spec("graph-only-gate-pinning", step)
    spec_checksum = run_spec_checksum(run_spec)
    port = InMemoryHarnessGraphTransitionPort()
    runtime = HarnessGraphControlPlaneRuntime(port)
    state = runtime.initialize(
        run_spec,
        graph,
        HarnessGraphPreflightPolicy(),
        run_spec_checksum=spec_checksum,
    )
    scheduler = HarnessScheduler()
    activation = scheduler.next_decision(state, graph=graph)
    assert activation is not None
    state = runtime.apply_decision(
        state,
        graph,
        activation,
        run_spec_checksum=spec_checksum,
        occurred_at=_NOW,
    )
    step_input = _step_input(step, state)
    expected = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(step_input,),
    )

    assert expected is not None
    assert expected.binding_versions["gate:0000"] == "AnalysisGate@1"
    tampered = replace(
        expected,
        binding_versions={
            **expected.binding_versions,
            "gate:0000": "AnalysisGate@2",
        },
    )
    port.commit_graph_decision(
        tampered,
        occurred_at=_NOW,
        expected_last_sequence=state.last_event_sequence,
    )
    kernel = HarnessPinnedDecisionKernel(
        graph,
        lambda replay_state, commit: scheduler.next_decision(
            replay_state,
            graph=graph,
            step_inputs=(
                ()
                if commit.decision.decision_type
                is HarnessGraphDecisionType.ACTIVATE_NODE
                else (step_input,)
            ),
        ),
    )

    with pytest.raises(EventReplayMismatchError, match="pinned decision kernel"):
        HarnessGraphHistoryReducer().rebuild(
            port.recover_graph(run_spec.run_id),
            verify_history=True,
            decision_kernel=kernel,
        )
    with pytest.raises(HarnessValidationError) as changed:
        HarnessPinnedDecisionKernel(changed_graph, lambda _state, _commit: None).verify_graph(
            graph
        )

    assert changed.value.code == "graph_replay_graph_mismatch"
    assert changed_graph.checksum != graph.checksum


def test_graph_only_missing_terminal_evidence_is_quarantined() -> None:
    _, graph = _compiled_graph()
    graph_ref = graph.graph_ref
    terminal_policy_ref = graph.terminal_policy_ref
    assert graph_ref is not None
    assert terminal_policy_ref is not None

    with pytest.raises(HarnessValidationError) as missing:
        HarnessGraphDecision(
            HarnessGraphDecisionType.COMPLETE_RUN,
            "graph-only-terminal-evidence",
            graph_ref=HarnessGraphReference.from_graph(graph),
            input_projection_checksum=checksum_for("terminal-input"),
            observation_checksum=checksum_for("terminal-observation"),
            reason_code="graph_terminal_succeeded",
            evidence_refs=(),
            binding_versions={"terminal_policy": terminal_policy_ref.exact_ref},
            payload={"outcome": "succeeded"},
        )

    diagnostic = quarantine_graph_replay_failure(missing.value)
    assert missing.value.code == "graph_terminal_evidence_missing"
    assert diagnostic.quarantined
    assert diagnostic.quarantine_reason == "graph_history_evidence_missing"

    valid = HarnessGraphDecision(
        HarnessGraphDecisionType.COMPLETE_RUN,
        "graph-only-terminal-evidence",
        graph_ref=HarnessGraphReference.from_graph(graph),
        input_projection_checksum=checksum_for("terminal-input"),
        observation_checksum=checksum_for("terminal-observation"),
        reason_code="graph_terminal_succeeded",
        evidence_refs=(checksum_for("terminal-evidence"),),
        binding_versions={"terminal_policy": terminal_policy_ref.exact_ref},
        payload={"outcome": "succeeded"},
    )
    with pytest.raises(HarnessValidationError) as decision_schema:
        replace(valid, schema_version=HARNESS_GRAPH_DECISION_SCHEMA)
    assert decision_schema.value.code == "graph_decision_schema_mismatch"


def test_graph_only_reference_rejects_legacy_identity_and_unknown_versions() -> None:
    _, graph = _compiled_graph()
    reference = HarnessGraphReference.from_graph(graph)
    payload = reference.to_dict()
    mixed = {
        **payload,
        "workflow_ref": HarnessContractReference(
            HarnessContractKind.WORKFLOW,
            "legacy-workflow",
            "1",
        ).to_dict(),
    }
    unknown_compiler = {
        **payload,
        "compiler_version": "newsroom.harness-graph-compiler/v999",
    }

    with pytest.raises(HarnessValidationError) as dual_identity:
        HarnessGraphReference.from_dict(mixed)
    with pytest.raises(HarnessValidationError) as compiler_version:
        HarnessGraphReference.from_dict(unknown_compiler)

    assert set(payload) == {
        "graph_id",
        "graph_ref",
        "schema_version",
        "compiler_version",
        "condition_policy_version",
        "checksum",
    }
    assert dual_identity.value.code == "invalid_graph_state_projection"
    assert compiler_version.value.code == "unsupported_graph_compiler"


def _compiled_graph(
    *,
    gate_ref: str = "AnalysisGate@1",
) -> tuple[HarnessStepSpec, NormalizedHarnessGraph]:
    step = HarnessStepSpec(
        "analyze",
        HarnessWorkerType.FUNCTION,
        output_key="analysis",
        quality_gate=gate_ref,
        metadata={
            "worker_id": "graph-only.analyze",
            "worker_version": "1",
            "activity_contract_version": "graph-only.analyze@1",
        },
    )
    graph_spec = HarnessGraphSpec(
        "graph-only.recovery",
        StepRef("analyze"),
        terminal_output_keys=("analysis",),
    )
    definition = HarnessGraphDefinition(
        graph_id=graph_spec.graph_id,
        graph_version="1",
        root=graph_spec,
        activities=(step,),
        leaf_activity_bindings=(
            HarnessGraphLeafBinding(
                "analyze",
                HarnessLeafActivityKind.FUNCTION,
                HarnessContractReference(
                    HarnessContractKind.WORKER,
                    "graph-only.analyze",
                    "1",
                ),
                HarnessContractReference(
                    HarnessContractKind.ACTIVITY,
                    "graph-only.analyze",
                    "1",
                ),
            ),
        ),
        task_plan_stage_bindings=(),
        committed_output_bindings=(),
        repair_bindings=(),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="graph-only.artifact-publication",
            version="1",
            handler="graph-only.artifact-publication@1",
            kind="artifact_publication",
            requires_approval=False,
            retry_limit=1,
            not_required_evidence_ref=checksum_for("publication-not-required"),
        ),
    )
    return step, HarnessGraphCompiler().compile(definition).graph


def _run_spec(run_id: str, step: HarnessStepSpec) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id="graph-only.recovery",
        steps=(step,),
        entry_step_id=step.step_id,
        graph=HarnessGraphSpec("graph-only.recovery", StepRef(step.step_id)),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_NOW)


def _step_input(
    step: HarnessStepSpec,
    state: HarnessGraphState,
) -> HarnessGraphStepSchedulingInput:
    node = state.node_instances[0]
    return HarnessGraphStepSchedulingInput(
        node.instance_id,
        step,
        StepLifecycleObservations.for_node(node),
        StepLifecycleBudget(
            max_turns=12,
            turns_used=0,
            max_replans=2,
            replans_used=0,
            max_retries_per_step=2,
            max_worker_calls=24,
            worker_calls_used=0,
        ),
    )


def _mapping_keys(value: Any) -> frozenset[str]:
    if isinstance(value, Mapping):
        return frozenset(value).union(
            *(_mapping_keys(item) for item in value.values())
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return frozenset().union(*(_mapping_keys(item) for item in value))
    return frozenset()
