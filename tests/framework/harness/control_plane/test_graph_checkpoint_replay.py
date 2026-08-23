from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.events.canonical import checksum_for
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
)
from framework.events.schema.catalog import (
    HARNESS_GRAPH_TRANSITION_EVENT_SCHEMAS,
    default_event_schema_catalog,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_checkpoint import (
    HarnessGraphCheckpoint,
    HarnessGraphCheckpointReader,
    HarnessGraphHistoryReducer,
    HarnessGraphStateReader,
    HarnessPinnedDecisionKernel,
    InMemoryHarnessGraphCheckpointStore,
    graph_history_evidence_ref,
)
from framework.harness.control_plane.graph_state import HarnessLoopIteration
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    HarnessRunResult,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.graph.dsl import HarnessGraphSpec, Sequence, StepRef
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
    HarnessStepSpec,
    HarnessWorkerType,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessLeafActivityBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.definition import (
    HarnessGraphDefinition,
    HarnessGraphLeafBinding,
)
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.side_effects.fake import (
    CountingHarnessSideEffectHandler,
    InMemoryHarnessSideEffectStore,
)
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.workers.result import HarnessWorkerResult
from framework.harness.runtime.activity_executor import (
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.runtime.graph_dispatcher import (
    HarnessGraphPhysicalActivityDispatcher,
)
from framework.harness import InMemoryHarnessNodeOutputResource
from framework.shared.attempts import AttemptSupervisor


_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def test_live_graph_admission_rejects_missing_dispatcher_before_durable_state() -> None:
    run_spec = _linear_run_spec("run-admission-dispatcher-required")
    event_port = InMemoryHarnessEventPort()
    terminal_store = InMemoryHarnessSideEffectStore()
    terminal_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "test.terminal@1",
                "artifact",
                CountingHarnessSideEffectHandler(
                    terminal_store,
                    disposition="accepted",
                ),
            ),
        )
    )
    authority = _linear_authority(
        (
            _FunctionWorker("first", {"first": True}),
            _FunctionWorker("second", {"second": True}),
        ),
        side_effect_registry=terminal_registry,
    )
    control_plane = HarnessControlPlane(
        event_port=event_port,
        side_effect_store=terminal_store,
        runtime_binding_authority=authority,
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(run_spec)

    assert captured.value.code == "graph_physical_dispatcher_missing"
    assert event_port.events == []
    recovery = event_port.recover_graph(run_spec.run_id)
    assert recovery.state is None
    assert recovery.expected_last_sequence == 0


def test_graph_history_rebuild_and_checkpoint_resume_are_pure_and_exact() -> None:
    control_plane, event_port, run_spec, _ = _completed_run("run-graph-checkpoint")
    recovery = event_port.recover_graph(run_spec.run_id)
    reducer = HarnessGraphHistoryReducer()

    rebuilt = reducer.rebuild(recovery)
    verified = control_plane.verify_graph_history(run_spec)
    checkpoint_state = recovery.projection_commits[
        len(recovery.projection_commits) // 2
    ].state
    checkpoint = HarnessGraphCheckpoint.from_state(
        "checkpoint-mid-run",
        checkpoint_state,
        created_at=_NOW,
        history_evidence_ref=graph_history_evidence_ref(
            recovery,
            through_sequence=checkpoint_state.last_event_sequence,
            projection_checksum=checkpoint_state.projection_checksum,
        ),
    )
    resumed = control_plane.verify_graph_history(
        run_spec,
        checkpoint=checkpoint,
    )

    assert rebuilt.state == control_plane.recover_graph(run_spec)
    assert verified.state == rebuilt.state
    assert resumed.state == rebuilt.state
    assert rebuilt.projection_checksum == recovery.state.projection_checksum
    assert rebuilt.verified_decision_checksums == ()
    assert verified.verified_decision_checksums
    assert resumed.verified_decision_checksums == verified.verified_decision_checksums
    assert resumed.applied_projection_sequences[0] > checkpoint.last_event_sequence
    assert rebuilt.pending_cause_checksums == ()


def test_graph_checkpoint_roundtrip_store_and_tamper_detection() -> None:
    _, event_port, run_spec, _ = _completed_run("run-checkpoint-roundtrip")
    state = event_port.recover_graph(run_spec.run_id).state
    assert state is not None
    checkpoint = HarnessGraphCheckpoint.from_state(
        "checkpoint-roundtrip",
        state,
        created_at=_NOW,
    )
    store = InMemoryHarnessGraphCheckpointStore()

    assert HarnessGraphCheckpoint.from_dict(checkpoint.to_dict()) == checkpoint
    assert store.save(checkpoint) == checkpoint
    assert store.load(checkpoint.checkpoint_id) == checkpoint

    tampered = checkpoint.to_dict()
    tampered["projection_checksum"] = checksum_for("tampered")
    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphCheckpoint.from_dict(tampered)
    assert captured.value.code == "graph_checkpoint_checksum_mismatch"


def test_verify_history_rejects_a_conflicting_pinned_decision_kernel() -> None:
    _, event_port, run_spec, _ = _completed_run("run-verify-decision-kernel")
    recovery = event_port.recover_graph(run_spec.run_id)

    kernel = HarnessPinnedDecisionKernel(
        recovery.graph,
        lambda _state, commit: replace(
            commit.decision,
            reason_code="different_replay_decision",
        ),
    )

    with pytest.raises(EventReplayMismatchError, match="pinned decision kernel"):
        HarnessGraphHistoryReducer().rebuild(
            recovery,
            verify_history=True,
            decision_kernel=kernel,
        )


def test_checkpoint_reader_quarantines_unknown_or_incompatible_graphs() -> None:
    _, event_port, run_spec, _ = _completed_run("run-checkpoint-quarantine")
    state = event_port.recover_graph(run_spec.run_id).state
    assert state is not None
    checkpoint = HarnessGraphCheckpoint.from_state(
        "checkpoint-quarantine",
        state,
        created_at=_NOW,
    )
    reader = HarnessGraphCheckpointReader()

    unknown = reader.read_or_quarantine(
        {"schema_version": "newsroom.harness-graph-checkpoint/v999"}
    )
    incompatible = reader.read_or_quarantine(
        checkpoint.to_dict(),
        expected_graph_ref=replace(
            checkpoint.graph_ref,
            checksum=checksum_for("another-graph"),
        ),
    )

    assert unknown.quarantined
    assert unknown.quarantine_reason == "legacy_orchestration_not_supported"
    assert incompatible.quarantined
    assert incompatible.quarantine_reason == "graph_checkpoint_graph_mismatch"


def test_replay_high_watermark_verifies_pending_decision_without_appending() -> None:
    control_plane, event_port, run_spec, _ = _completed_run("run-replay-high-watermark")
    recovery = event_port.recover_graph(run_spec.run_id)
    decision = recovery.decision_commits[len(recovery.decision_commits) // 2]
    event_count = len(event_port.events)

    report = control_plane.verify_graph_history(
        run_spec,
        through_sequence=decision.sequence,
    )

    assert report.through_sequence == decision.sequence
    assert report.pending_cause_checksums == (decision.decision.decision_checksum,)
    assert report.verified_decision_checksums[-1] == (
        decision.decision.decision_checksum
    )
    assert len(event_port.events) == event_count


def test_verify_history_without_a_pinned_kernel_is_quarantined() -> None:
    _, event_port, run_spec, _ = _completed_run("run-replay-kernel-missing")

    result = HarnessGraphHistoryReducer().rebuild_or_quarantine(
        event_port.recover_graph(run_spec.run_id),
        verify_history=True,
    )

    assert result.quarantined
    assert result.quarantine_reason == "graph_history_evidence_missing"
    assert result.report is None


@pytest.mark.parametrize(
    ("failure", "reason"),
    (
        (
            EventStoreCorruptionError("corrupt graph source"),
            "corrupt_graph_history",
        ),
        (
            EventIncompleteHistoryError("missing graph evidence"),
            "graph_history_evidence_missing",
        ),
        (
            HarnessValidationError(
                "unknown graph event version",
                code="unsupported_graph_event_version",
            ),
            "unsupported_graph_history_version",
        ),
    ),
)
def test_control_plane_quarantines_corrupt_unknown_or_incomplete_history(
    failure: Exception,
    reason: str,
) -> None:
    control_plane, event_port, run_spec, _ = _completed_run(
        f"run-source-quarantine-{reason}"
    )

    def fail_recovery(_run_id: str):
        raise failure

    event_port.recover_graph = fail_recovery  # type: ignore[method-assign]

    result = control_plane.verify_graph_history_or_quarantine(run_spec)

    assert result.quarantined
    assert result.quarantine_reason == reason
    assert result.report is None


def test_verify_history_never_uses_live_scheduler_workers_or_gates() -> None:
    control_plane, event_port, run_spec, expected = _completed_run(
        "run-no-live-replay-fallback"
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("live replay fallback was invoked")

    control_plane.scheduler = forbidden  # type: ignore[assignment]
    control_plane.plan_gates = (forbidden,)  # type: ignore[assignment]
    control_plane.verify_gates = (forbidden,)  # type: ignore[assignment]
    event_port.accept_activity = forbidden  # type: ignore[method-assign]
    event_count = len(event_port.events)

    report = control_plane.verify_graph_history(run_spec)

    assert expected.state is not None
    assert report.state == expected.state
    assert len(event_port.events) == event_count


def test_logical_graph_transition_schemas_are_reference_only_and_registered() -> None:
    catalog = default_event_schema_catalog()
    checksum = checksum_for("transition")
    payload = {
        "transition_type": "activate_node",
        "graph_checksum": checksum,
        "projection_checksum": checksum,
        "cause_checksum": checksum,
        "node_instance_id": "node-instance-1",
        "attempt": 1,
        "evidence_refs": [checksum],
        "payload_refs": {"output": checksum},
        "diagnostic_refs": [],
    }

    for event_type, schema in HARNESS_GRAPH_TRANSITION_EVENT_SCHEMAS.items():
        validated = catalog.validate(
            event_type,
            schema,
            {"schema_version": schema, **payload},
        )
        assert validated["schema_version"] == schema
        assert "payload" not in validated

def test_parallel_any_winner_replays_from_recorded_sequence() -> None:
    from tests.framework.harness.control_plane.test_parallel_graph_control_plane import (
        _control_plane,
        _parallel_any_run_spec,
    )

    run_spec = _parallel_any_run_spec(
        "run-replay-parallel-any",
        cancellation_policy="wait_for_losers",
    )
    event_port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port, [])
    result = control_plane.run(run_spec)

    assert result.state is not None
    winner = result.state.join_states[0].winner_branch_id
    report = control_plane.verify_graph_history(run_spec)

    assert winner == "left-branch"
    assert report.state.join_states[0].winner_branch_id == winner
    assert report.projection_checksum == result.state.projection_checksum


def test_timer_wait_wake_replays_without_reading_current_clock() -> None:
    from tests.framework.harness.control_plane.test_wait_graph_control_plane import (
        _CREATED_AT,
        _control_plane,
        _scope,
        _wait_run_spec,
    )
    from framework.harness.waits.models import HarnessWaitTimerWakeRecord

    run_spec = _wait_run_spec("run-replay-timer-wait", wait_kind="timer")
    event_port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port)
    waiting = control_plane.run(run_spec).state
    assert waiting is not None
    registration = waiting.wait_registrations[0]
    control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitTimerWakeRecord(
            _scope(run_spec.run_id, registration),
            registration.deadline_ref,
            checksum_for("recorded-timer-wake"),
            0,
        ),
        occurred_at=_CREATED_AT,
    )
    completed = control_plane.recover_and_run(run_spec)

    assert completed.state is not None
    report = control_plane.verify_graph_history(run_spec)
    assert report.state.wait_registrations[0].status.value == "resumed"
    assert report.projection_checksum == completed.state.projection_checksum


def test_completed_compensation_replays_from_committed_effect_evidence() -> None:
    from tests.framework.harness.control_plane.test_compensation_entry_durability import (
        _parallel_compensation_fixture,
    )
    from framework.harness.graph.validation import HarnessGraphPreflightPolicy
    from framework.harness.graph.validation import HarnessGraphPreflight

    fixture = _parallel_compensation_fixture("run-replay-completed-compensation")
    fixture.control_plane.graph_preflight = HarnessGraphPreflight(
        policy=HarnessGraphPreflightPolicy(
            max_node_activations=30,
            max_active_nodes=8,
            max_parallelism=1,
            max_compensations=4,
        )
    )
    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    assert len(result.state.compensation_stack) == 1
    assert result.state.compensation_stack[0].status.value == "succeeded"
    report = fixture.control_plane.verify_graph_history(fixture.run_spec)

    assert report.state.compensation_stack == result.state.compensation_stack
    assert report.projection_checksum == result.state.projection_checksum


def _completed_run(
    run_id: str,
) -> tuple[
    HarnessControlPlane,
    InMemoryHarnessEventPort,
    HarnessRunSpec,
    HarnessRunResult,
]:
    run_spec = _linear_run_spec(run_id)
    event_port = InMemoryHarnessEventPort()
    first = _FunctionWorker("first", {"first": True})
    second = _FunctionWorker("second", {"second": True})
    terminal_store = InMemoryHarnessSideEffectStore()
    terminal_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "test.terminal@1",
                "artifact",
                CountingHarnessSideEffectHandler(
                    terminal_store,
                    disposition="accepted",
                ),
            ),
        )
    )
    control_plane = HarnessControlPlane(
        event_port=event_port,
        side_effect_store=terminal_store,
        runtime_binding_authority=_linear_authority(
            (first, second),
            side_effect_registry=terminal_registry,
        ),
    )
    _install_local_physical_dispatcher(control_plane)
    result = control_plane.run(run_spec)
    return control_plane, event_port, run_spec, result


def test_public_run_result_preserves_duplicate_step_instances() -> None:
    control_plane, _event_port, run_spec, result = _completed_run(
        "run-result-instance-identity"
    )
    source_node = next(
        node
        for node in result.state.node_instances
        if node.step_id == "first"
    )
    duplicate_identity = replace(
        source_node.identity,
        branch_path=("loop",),
        iteration_vector=(HarnessLoopIteration("result-loop", 0),),
        activation_ordinal=source_node.identity.activation_ordinal + 100,
    )
    duplicate_node = replace(
        source_node,
        identity=duplicate_identity,
        evidence_refs=(),
        output_refs={},
    )
    projected_state = replace(
        result.state,
        node_instances=(*result.state.node_instances, duplicate_node),
        projection_checksum=None,
    )
    duplicate_worker_result = HarnessWorkerResult(
        "succeeded",
        output={"first": "duplicate"},
    )
    control_plane._graph_worker_results[run_spec.run_id][
        duplicate_node.instance_id
    ] = duplicate_worker_result

    projected = control_plane._graph_result(
        run_spec,
        projected_state,
        decisions=[],
    )

    assert set(projected.worker_results) == {
        source_node.instance_id,
        duplicate_node.instance_id,
        next(
            node.instance_id
            for node in result.state.node_instances
            if node.step_id == "second"
        ),
    }
    assert projected.worker_results[duplicate_node.instance_id] is duplicate_worker_result


def _install_local_physical_dispatcher(
    control_plane: HarnessControlPlane,
) -> None:
    """Assemble the explicit test physical boundary used by Graph runs."""

    executor = HarnessGraphPhysicalActivityExecutor(
        binding_authority=control_plane.runtime_binding_authority,
        input_resolver=control_plane,
        node_output_resource=InMemoryHarnessNodeOutputResource(),
        result_committer=None,
        supervisor=AttemptSupervisor(),
    )
    control_plane.install_graph_activity_dispatcher(
        HarnessGraphPhysicalActivityDispatcher(
            executor=executor,
            graph_resolver=control_plane.graph_for_activity,
            input_resolver=control_plane,
            accept=control_plane.accept_graph_activity_for_execution,
            record_call_marker=control_plane.record_graph_activity_call_marker,
            record_result=control_plane.record_graph_activity_result_event,
            apply_result=control_plane.commit_physical_graph_result,
        )
    )


def _linear_run_spec(run_id: str) -> HarnessRunSpec:
    graph = HarnessGraphSpec(
        f"graph-{run_id}",
        Sequence((StepRef("first"), StepRef("second"))),
    )
    activities = (
        HarnessStepSpec("first", HarnessWorkerType.FUNCTION, output_key="first_output"),
        HarnessStepSpec("second", HarnessWorkerType.FUNCTION, output_key="second_output"),
    )
    definition = HarnessGraphDefinition(
        graph_id=graph.graph_id,
        graph_version="1",
        root=graph,
        activities=activities,
        leaf_activity_bindings=tuple(
            _leaf_definition_binding(activity.step_id) for activity in activities
        ),
        task_plan_stage_bindings=(),
        committed_output_bindings=(),
        repair_bindings=(),
        terminal_side_effect_policy=_terminal_policy(),
    )
    return HarnessRunSpec(
        run_id,
        graph=definition,
        metadata={
            "identity_scope_ref": checksum_for({"identity": run_id}),
            "subject_scope_ref": checksum_for({"subject": run_id}),
        },
        created_at=_NOW,
    )


class _FunctionWorker:
    worker_version = "1"
    worker_type = HarnessWorkerType.FUNCTION

    def __init__(self, worker_id: str, output: dict[str, bool]) -> None:
        self.worker_id = worker_id
        self._output = output

    def execute(self, _task: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult("succeeded", output=self._output)


class _FunctionActivity:
    activity_contract_id = "test.function.activity"
    activity_contract_version = "1"
    capabilities = HarnessActivityCapabilities()

    def dispatch(self, _request: dict) -> None:
        return None


def _linear_authority(
    workers: tuple[_FunctionWorker, ...],
    *,
    side_effect_registry: HarnessSideEffectRegistry,
) -> HarnessRuntimeBindingAuthority:
    activity_ref = HarnessContractReference(
        HarnessContractKind.ACTIVITY,
        "test.function.activity",
        "1",
    )
    worker_bindings = tuple(
        HarnessWorkerBinding(
            HarnessContractReference(
                HarnessContractKind.WORKER,
                worker.worker_id,
                worker.worker_version,
            ),
            HarnessWorkerType.FUNCTION,
            worker,
        )
        for worker in workers
    )
    return HarnessRuntimeBindingAuthority(
        workers=worker_bindings,
        activities=(HarnessActivityContractBinding(activity_ref, _FunctionActivity()),),
        leaf_activities=tuple(
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                worker.reference,
                activity_ref,
            )
            for worker in worker_bindings
        ),
        side_effect_registry=side_effect_registry,
    )


def _leaf_definition_binding(activity_id: str) -> HarnessGraphLeafBinding:
    return HarnessGraphLeafBinding(
        activity_id=activity_id,
        leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
        worker_ref=HarnessContractReference(
            HarnessContractKind.WORKER,
            activity_id,
            "1",
        ),
        activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            "test.function.activity",
            "1",
        ),
    )


def _terminal_policy() -> HarnessTerminalSideEffectPolicy:
    return HarnessTerminalSideEffectPolicy(
        policy_id="test.terminal",
        version="1",
        handler="test.terminal@1",
        kind="artifact",
        requires_approval=False,
        retry_limit=1,
        not_required_evidence_ref=checksum_for("terminal-not-required"),
    )
