from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane import graph_application
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
)
from framework.harness.control_plane.gates import OutputSchemaGate
from framework.harness.control_plane.graph_decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphObservationType,
)
from framework.harness.control_plane.graph_state import (
    HarnessNodeInstanceStatus,
    HarnessWaitStatus,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.policy import HarnessBudget
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.graph.dsl import (
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
    Wait,
    WaitTimeoutPolicy,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workflow.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
)
from framework.harness.workers.result import HarnessWorkerResult
from framework.harness.waits.models import (
    HarnessEarlySignalRetentionPolicy,
    HarnessWaitApprovalEvidenceRecord,
    HarnessWaitCancellationRecord,
    HarnessWaitScope,
    HarnessWaitSignal,
    HarnessWaitTimeoutRecord,
    HarnessWaitTimerWakeRecord,
)


_CREATED_AT = datetime(2026, 7, 31, 9, 0, tzinfo=UTC)


class _RecordingTimerPort:
    def __init__(self, *, fail_registration: bool = False) -> None:
        self.fail_registration = fail_registration
        self.registrations = {}
        self.cancelled_refs: list[str] = []

    def register_timer(self, registration) -> None:
        if self.fail_registration:
            raise RuntimeError("timer adapter unavailable")
        self.registrations[registration.registration_ref] = registration

    def cancel_timer(self, registration) -> None:
        self.registrations.pop(registration.registration_ref, None)
        self.cancelled_refs.append(registration.registration_ref)


def test_signal_wait_survives_restart_and_duplicate_delivery() -> None:
    run_spec = _wait_run_spec("run-wait-restart")
    port = InMemoryHarnessEventPort()
    first = _control_plane(port)

    waiting_result = first.run(run_spec)

    assert waiting_result.graph_state is not None
    waiting = waiting_result.graph_state
    assert waiting.lifecycle is RunLifecycle.WAITING
    registration = waiting.wait_registrations[0]
    assert registration.status is HarnessWaitStatus.REGISTERED
    scope = _scope(run_spec.run_id, registration)
    signal = HarnessWaitSignal(
        "signal-1",
        scope,
        checksum_for({"approved": True}),
        0,
    )

    restarted = _control_plane(port)
    resumed = restarted.accept_graph_wait_cause(
        run_spec,
        signal,
        occurred_at=_CREATED_AT,
    )
    sequence_after_signal = resumed.last_event_sequence

    assert resumed.lifecycle is RunLifecycle.RUNNING
    assert resumed.wait_registrations[0].status is HarnessWaitStatus.RESUMED
    assert resumed.signal_inbox[0].status.value == "matched"
    duplicate = restarted.accept_graph_wait_cause(
        run_spec,
        HarnessWaitSignal(
            "signal-1",
            scope,
            signal.payload_ref,
            999,
        ),
        occurred_at=_CREATED_AT,
    )
    assert duplicate.last_event_sequence == sequence_after_signal

    completed = restarted.recover_and_run(run_spec)

    assert completed.graph_state is not None
    assert completed.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED
    assert (
        _node(completed.graph_state, "after").status
        is HarnessNodeInstanceStatus.SUCCEEDED
    )


def test_concurrent_identical_signal_is_committed_once() -> None:
    run_spec = _wait_run_spec("run-wait-concurrent-duplicate")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    scope = _scope(run_spec.run_id, waiting.wait_registrations[0])
    barrier = Barrier(2)

    def deliver() -> object:
        barrier.wait()
        return control_plane.accept_graph_wait_cause(
            run_spec,
            HarnessWaitSignal(
                "concurrent-signal",
                scope,
                checksum_for({"payload": "same"}),
                0,
            ),
            occurred_at=_CREATED_AT,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: deliver(), range(2)))

    assert all(
        result.wait_registrations[0].status is HarnessWaitStatus.RESUMED
        for result in results
    )
    recovery = port.recover_graph(run_spec.run_id)
    wait_causes = tuple(
        item
        for item in recovery.observation_commits
        if item.observation.observation_type.value == "wait_cause"
    )
    assert len(wait_causes) == 1


def test_concurrent_conflicting_signal_identity_commits_one_cause() -> None:
    run_spec = _wait_run_spec("run-wait-concurrent-conflict")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    scope = _scope(run_spec.run_id, waiting.wait_registrations[0])
    barrier = Barrier(2)

    def deliver(payload: str) -> tuple[str, object]:
        barrier.wait()
        try:
            state = control_plane.accept_graph_wait_cause(
                run_spec,
                HarnessWaitSignal(
                    "conflicting-signal",
                    scope,
                    checksum_for({"payload": payload}),
                    0,
                ),
                occurred_at=_CREATED_AT,
            )
        except HarnessValidationError as error:
            return "error", error.code
        return "accepted", state

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(
            executor.submit(deliver, payload) for payload in ("first", "second")
        )
        results = tuple(future.result() for future in futures)

    accepted = tuple(value for status, value in results if status == "accepted")
    errors = tuple(value for status, value in results if status == "error")
    assert len(accepted) == 1
    assert accepted[0].wait_registrations[0].status is HarnessWaitStatus.RESUMED
    assert errors == ("wait_signal_identity_conflict",)
    wait_causes = tuple(
        item
        for item in port.recover_graph(run_spec.run_id).observation_commits
        if item.observation.observation_type is HarnessGraphObservationType.WAIT_CAUSE
    )
    assert len(wait_causes) == 1


def test_signal_before_registration_is_matched_only_after_register_commit() -> None:
    run_spec = _wait_run_spec("run-wait-early")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    state = control_plane.initialize_graph(run_spec)
    activation = control_plane.next_graph_decision(run_spec, state)
    assert activation is not None
    assert activation.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
    ready = control_plane.apply_graph_decision(
        run_spec,
        state,
        activation,
        occurred_at=_CREATED_AT,
    )
    register = control_plane.next_graph_decision(run_spec, ready)
    assert register is not None
    assert register.decision_type is HarnessGraphDecisionType.REGISTER_WAIT
    scope = control_plane.inspect_graph_wait_scope(
        run_spec,
        register.node_instance_id,
    )

    early = control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitSignal(
            "signal-early",
            scope,
            checksum_for({"value": "ready"}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    assert early.wait_registrations == ()
    assert early.signal_inbox[0].status.value == "early"
    recovery = port.recover_graph(run_spec.run_id)
    register_after_signal = control_plane.next_graph_decision(
        run_spec,
        early,
        graph_context=control_plane._graph_evaluation_context(
            run_spec,
            early,
            recovery,
        ),
    )
    assert register_after_signal is not None
    registered = control_plane.apply_graph_decision(
        run_spec,
        early,
        register_after_signal,
        occurred_at=_CREATED_AT,
    )
    assert registered.wait_registrations[0].status is HarnessWaitStatus.RESUMED
    assert registered.signal_inbox[0].status.value == "matched"

    completed = control_plane.recover_and_run(run_spec)
    assert completed.graph_state is not None
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED


def test_matched_signal_is_pruned_before_later_valid_signal_enters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        graph_application,
        "_WAIT_SIGNAL_RETENTION_POLICY",
        HarnessEarlySignalRetentionPolicy(
            max_signals=2,
            max_signals_per_scope=2,
            sequence_window=2,
        ),
    )
    run_spec = _two_wait_run_spec("run-wait-retention")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    first_waiting = control_plane.run(run_spec).graph_state
    assert first_waiting is not None
    first_registration = next(
        item for item in first_waiting.wait_registrations if item.wait_id == "first-wait"
    )

    first_resumed = control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitSignal(
            "first-signal",
            _scope(run_spec.run_id, first_registration),
            checksum_for({"payload": "first"}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )
    assert [item.signal.signal_id for item in first_resumed.signal_inbox] == [
        "first-signal"
    ]

    second_waiting = control_plane.recover_and_run(run_spec).graph_state
    assert second_waiting is not None
    assert second_waiting.lifecycle is RunLifecycle.WAITING
    assert [item.signal.signal_id for item in second_waiting.signal_inbox] == [
        "first-signal"
    ]
    second_registration = next(
        item
        for item in second_waiting.wait_registrations
        if item.wait_id == "second-wait"
    )

    second_resumed = control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitSignal(
            "second-signal",
            _scope(run_spec.run_id, second_registration),
            checksum_for({"payload": "second"}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    assert [item.signal.signal_id for item in second_resumed.signal_inbox] == [
        "second-signal"
    ]
    assert second_resumed.wait_registrations[-1].status is HarnessWaitStatus.RESUMED


def test_early_signal_rejects_wrong_tenant_and_correlation_without_commit() -> None:
    run_spec = _wait_run_spec("run-wait-wrong-scope")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    state = control_plane.initialize_graph(run_spec)
    activation = control_plane.next_graph_decision(run_spec, state)
    assert activation is not None
    ready = control_plane.apply_graph_decision(
        run_spec,
        state,
        activation,
        occurred_at=_CREATED_AT,
    )
    register = control_plane.next_graph_decision(run_spec, ready)
    assert register is not None
    scope = control_plane.inspect_graph_wait_scope(
        run_spec,
        register.node_instance_id,
    )
    before = port.recover_graph(run_spec.run_id).expected_last_sequence

    for wrong_scope in (
        HarnessWaitScope(
            **{
                **scope.to_dict(),
                "tenant_scope_ref": checksum_for("wrong-tenant"),
            }
        ),
        HarnessWaitScope(
            **{
                **scope.to_dict(),
                "correlation_ref": checksum_for("wrong-correlation"),
            }
        ),
    ):
        with pytest.raises(HarnessValidationError) as captured:
            control_plane.accept_graph_wait_cause(
                run_spec,
                HarnessWaitSignal(
                    "signal-wrong",
                    wrong_scope,
                    checksum_for({"value": "wrong"}),
                    0,
                ),
                occurred_at=_CREATED_AT,
            )
        assert captured.value.code == "graph_wait_cause_scope_mismatch"

    assert port.recover_graph(run_spec.run_id).expected_last_sequence == before


def test_generic_observation_api_rejects_wait_cause_bypass() -> None:
    run_spec = _wait_run_spec("run-wait-observation-bypass")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    registration = waiting.wait_registrations[0]
    event_sequence = port.recover_graph(run_spec.run_id).expected_last_sequence + 1
    signal = HarnessWaitSignal(
        "bypass-signal",
        _scope(run_spec.run_id, registration),
        checksum_for({"bypass": True}),
        event_sequence,
    )
    observation = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.WAIT_CAUSE,
        "signal-wait",
        registration.node_instance_id,
        0,
        event_sequence,
        HarnessContractReference(HarnessContractKind.WAIT, "newsroom.wait", "1"),
        signal.signal_ref,
        payload={"cause_kind": "signal", "record": signal.to_dict()},
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_CREATED_AT,
        )

    assert captured.value.code == "graph_wait_typed_boundary_required"


def test_timer_wake_uses_recorded_cause_and_resume_route() -> None:
    run_spec = _wait_run_spec(
        "run-wait-timer",
        wait_kind="timer",
    )
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    registration = waiting.wait_registrations[0]
    scope = _scope(run_spec.run_id, registration)

    resumed = control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitTimerWakeRecord(
            scope,
            registration.deadline_ref,
            checksum_for({"timer": "wake-1"}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    assert resumed.lifecycle is RunLifecycle.RUNNING
    assert resumed.wait_registrations[0].status is HarnessWaitStatus.RESUMED
    completed = control_plane.recover_and_run(run_spec)
    assert completed.graph_state is not None
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED


def test_timeout_route_skips_the_normal_sequence_successor() -> None:
    run_spec = _timeout_route_run_spec("run-wait-timeout-route")
    port = InMemoryHarnessEventPort()
    calls: list[str] = []
    control_plane = _control_plane(port, calls=calls)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    registration = waiting.wait_registrations[0]

    timed_out = control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitTimeoutRecord(
            _scope(run_spec.run_id, registration),
            registration.deadline_ref,
            checksum_for({"timeout": "route"}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    assert timed_out.wait_registrations[0].status is HarnessWaitStatus.TIMED_OUT
    completed = control_plane.recover_and_run(run_spec)
    assert completed.graph_state is not None
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED
    assert calls == ["timeout"]
    assert not any(
        item.identity.node_id == "normal"
        for item in completed.graph_state.node_instances
    )


@pytest.mark.parametrize(
    ("action", "lifecycle", "outcome"),
    (
        ("halt", RunLifecycle.HALTED, RunOutcome.NONE),
        ("fail", RunLifecycle.COMPLETED, RunOutcome.FAILED),
    ),
)
def test_timeout_halt_and_fail_have_distinct_terminal_semantics(
    action: str,
    lifecycle: RunLifecycle,
    outcome: RunOutcome,
) -> None:
    run_spec = _wait_run_spec(
        f"run-wait-timeout-{action}",
        timeout_policy=WaitTimeoutPolicy(action),
    )
    port = InMemoryHarnessEventPort()
    calls: list[str] = []
    control_plane = _control_plane(port, calls=calls)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    registration = waiting.wait_registrations[0]
    control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitTimeoutRecord(
            _scope(run_spec.run_id, registration),
            registration.deadline_ref,
            checksum_for({"timeout": action}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    terminal = control_plane.recover_and_run(run_spec).graph_state

    assert terminal is not None
    assert terminal.lifecycle is lifecycle
    assert terminal.outcome is outcome
    assert calls == []


def test_timer_registration_is_post_commit_and_retried_during_recovery() -> None:
    run_spec = _wait_run_spec("run-wait-timer-recovery", wait_kind="timer")
    port = InMemoryHarnessEventPort()
    failing_timer = _RecordingTimerPort(fail_registration=True)
    control_plane = _control_plane(port, timer_wake_port=failing_timer)

    with pytest.raises(RuntimeError, match="timer adapter unavailable"):
        control_plane.run(run_spec)

    durable = port.recover_graph(run_spec.run_id).state
    assert durable is not None
    assert len(durable.wait_registrations) == 1
    assert durable.wait_registrations[0].status is HarnessWaitStatus.REGISTERED

    recovered_timer = _RecordingTimerPort()
    restarted = _control_plane(port, timer_wake_port=recovered_timer)
    recovered = restarted.recover_graph(run_spec)
    registration = recovered.wait_registrations[0]
    scope = _scope(run_spec.run_id, registration)
    registration_ref = _registration_ref(recovered, registration)
    assert registration_ref in recovered_timer.registrations

    restarted.accept_graph_wait_cause(
        run_spec,
        HarnessWaitTimerWakeRecord(
            scope,
            registration.deadline_ref,
            checksum_for({"timer": "recovered-wake"}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    assert registration_ref not in recovered_timer.registrations
    assert recovered_timer.cancelled_refs[-1] == registration_ref


def test_approval_and_cancellation_are_generic_wait_causes() -> None:
    approval_spec = _wait_run_spec(
        "run-wait-approval",
        wait_kind="approval",
    )
    approval_port = InMemoryHarnessEventPort()
    approval_plane = _control_plane(approval_port)
    waiting = approval_plane.run(approval_spec).graph_state
    assert waiting is not None
    registration = waiting.wait_registrations[0]
    scope = _scope(approval_spec.run_id, registration)

    approved = approval_plane.accept_graph_wait_cause(
        approval_spec,
        HarnessWaitApprovalEvidenceRecord(
            scope,
            checksum_for({"approval_id": "approval-1"}),
            checksum_for({"actor": "reviewer"}),
            True,
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    assert approved.wait_registrations[0].status is HarnessWaitStatus.RESUMED
    assert _node(approved, "approval-wait").metadata["approval_granted"] is True
    assert (
        approval_plane.recover_and_run(approval_spec).graph_state.outcome
        is RunOutcome.SUCCEEDED
    )

    cancel_spec = _wait_run_spec("run-wait-cancel")
    cancel_plane = _control_plane(InMemoryHarnessEventPort())
    cancel_waiting = cancel_plane.run(cancel_spec).graph_state
    assert cancel_waiting is not None
    cancel_registration = cancel_waiting.wait_registrations[0]
    cancelled = cancel_plane.accept_graph_wait_cause(
        cancel_spec,
        HarnessWaitCancellationRecord(
            _scope(cancel_spec.run_id, cancel_registration),
            checksum_for({"cancel": "operator-1"}),
            checksum_for({"actor": "operator"}),
            "operator_cancelled",
            0,
        ),
        occurred_at=_CREATED_AT,
    )
    assert cancelled.wait_registrations[0].status is HarnessWaitStatus.CANCELLED
    cancelled_run = cancel_plane.recover_and_run(cancel_spec).graph_state
    assert cancelled_run is not None
    assert cancelled_run.lifecycle is RunLifecycle.COMPLETED
    assert cancelled_run.outcome is RunOutcome.CANCELLED


def test_approval_resume_wrapper_uses_explicit_generic_wait_registration() -> None:
    run_spec = _wait_run_spec(
        "run-wait-approval-wrapper",
        wait_kind="approval",
    )
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None

    completed = control_plane.resume_after_approval(run_spec, approved=True)

    assert completed.graph_state is not None
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED
    wait_causes = tuple(
        item.observation
        for item in port.recover_graph(run_spec.run_id).observation_commits
        if item.observation.observation_type is HarnessGraphObservationType.WAIT_CAUSE
    )
    assert len(wait_causes) == 1
    assert wait_causes[0].payload["cause_kind"] == "approval"


def test_parallel_branch_continues_while_sibling_waits() -> None:
    run_spec = _parallel_wait_run_spec("run-parallel-wait")
    port = InMemoryHarnessEventPort()
    calls: list[str] = []
    control_plane = _control_plane(port, calls=calls, max_active_nodes=4)

    waiting = control_plane.run(run_spec).graph_state

    assert waiting is not None
    assert waiting.lifecycle is RunLifecycle.WAITING
    assert calls == ["fast"]
    assert _node(waiting, "fast").status is HarnessNodeInstanceStatus.SUCCEEDED
    registration = waiting.wait_registrations[0]
    control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitSignal(
            "parallel-signal",
            _scope(run_spec.run_id, registration),
            checksum_for({"resume": True}),
            0,
        ),
        occurred_at=_CREATED_AT,
    )

    completed = control_plane.recover_and_run(run_spec)
    assert completed.graph_state is not None
    assert completed.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED


def test_wait_registration_resolves_declared_verified_output_path() -> None:
    run_id = "run-wait-verified-output"
    tenant_ref = checksum_for({"tenant": run_id})
    identity_ref = checksum_for({"identity": run_id})
    producer = HarnessStepSpec(
        "produce",
        "script",
        output_key="token",
        quality_gate="output_schema@1",
        metadata={
            "step_version": "1",
            "worker_version": "1",
            "control_fact_paths": ("request_id",),
        },
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=(producer,),
        entry_step_id="produce",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Sequence(
                (
                    StepRef("produce"),
                    Wait(
                        "verified-wait",
                        "signal",
                        {
                            "request_id": (
                                "node.outputs.produce.token.request_id"
                            )
                        },
                        "newsroom.wait",
                        "1",
                        "graph.inputs.tenant_scope_ref",
                        "graph.inputs.identity_scope_ref",
                    ),
                )
            ),
            input_keys=("identity_scope_ref", "tenant_scope_ref"),
        ),
    )
    run_spec = HarnessRunSpec(
        run_id,
        workflow,
        inputs={
            "tenant_scope_ref": tenant_ref,
            "identity_scope_ref": identity_ref,
        },
        metadata={
            "tenant_scope_ref": tenant_ref,
            "identity_scope_ref": identity_ref,
        },
        budget=HarnessBudget.safe_default(),
        created_at=_CREATED_AT,
    )
    output_gate = OutputSchemaGate()
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        verify_gates=(output_gate,),
        gate_registry=DeterministicGateRegistry(
            (
                    GateRegistration(
                        GateReference.parse("output_schema@1"),
                        output_gate,
                ),
            )
        ),
        worker_registry={
            "produce": lambda task: HarnessWorkerResult(
                "succeeded",
                output={"request_id": "verified-request"},
            )
        },
    )

    waiting = control_plane.run(run_spec).graph_state

    assert waiting is not None
    assert waiting.lifecycle is RunLifecycle.WAITING
    assert waiting.wait_registrations[0].correlation_ref == checksum_for(
        {"request_id": "verified-request"}
    )


def _control_plane(
    port: InMemoryHarnessEventPort,
    *,
    calls: list[str] | None = None,
    max_active_nodes: int = 1,
    timer_wake_port=None,
) -> HarnessControlPlane:
    worker_calls = calls if calls is not None else []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(str(task["step_id"]))
        return HarnessWorkerResult("succeeded", output=task)

    return HarnessControlPlane(
        event_port=port,
        worker_registry={
            "after": worker,
            "fast": worker,
            "normal": worker,
            "timeout": worker,
        },
        graph_preflight=HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(
                max_active_nodes=max_active_nodes,
                max_parallelism=1,
            )
        ),
        timer_wake_port=timer_wake_port,
    )


def _wait_run_spec(
    run_id: str,
    *,
    wait_kind: str = "signal",
    timeout_policy: WaitTimeoutPolicy | None = None,
) -> HarnessRunSpec:
    wait_id = "approval-wait" if wait_kind == "approval" else "signal-wait"
    deadline_path = (
        "graph.inputs.deadline_ref"
        if wait_kind == "timer" or timeout_policy is not None
        else None
    )
    after = HarnessStepSpec(
        "after",
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    inputs = {
        "request_id": f"request-{run_id}",
        "tenant_scope_ref": checksum_for({"tenant": run_id}),
        "identity_scope_ref": checksum_for({"identity": run_id}),
        "deadline_ref": checksum_for({"deadline": "2026-08-01T00:00:00Z"}),
    }
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=(after,),
        entry_step_id="after",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Sequence(
                (
                    Wait(
                        wait_id,
                        wait_kind,
                        {"request_id": "graph.inputs.request_id"},
                        "newsroom.wait",
                        "1",
                        "graph.inputs.tenant_scope_ref",
                        "graph.inputs.identity_scope_ref",
                        timeout_policy=timeout_policy,
                        deadline_input_path=deadline_path,
                    ),
                    StepRef("after"),
                )
            ),
            input_keys=tuple(sorted(inputs)),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        inputs=inputs,
        metadata={
            "tenant_scope_ref": inputs["tenant_scope_ref"],
            "identity_scope_ref": inputs["identity_scope_ref"],
            "subject_scope_ref": checksum_for({"subject": run_id}),
        },
        budget=HarnessBudget.safe_default(),
        created_at=_CREATED_AT,
    )


def _two_wait_run_spec(run_id: str) -> HarnessRunSpec:
    base = _wait_run_spec(run_id)
    inputs = dict(base.inputs)
    after = HarnessStepSpec(
        "after",
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )

    def wait(wait_id: str) -> Wait:
        return Wait(
            wait_id,
            "signal",
            {"request_id": "graph.inputs.request_id"},
            "newsroom.wait",
            "1",
            "graph.inputs.tenant_scope_ref",
            "graph.inputs.identity_scope_ref",
        )

    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=(after,),
        entry_step_id="after",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Sequence(
                (
                    wait("first-wait"),
                    wait("second-wait"),
                    StepRef("after"),
                )
            ),
            input_keys=tuple(sorted(inputs)),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        inputs=inputs,
        metadata=dict(base.metadata),
        budget=HarnessBudget.safe_default(),
        created_at=_CREATED_AT,
    )


def _timeout_route_run_spec(run_id: str) -> HarnessRunSpec:
    base = _wait_run_spec(run_id)
    inputs = dict(base.inputs)
    steps = tuple(
        HarnessStepSpec(
            step_id,
            "script",
            metadata={"step_version": "1", "worker_version": "1"},
        )
        for step_id in ("normal", "timeout")
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=steps,
        entry_step_id="normal",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Sequence(
                (
                    Wait(
                        "signal-wait",
                        "signal",
                        {"request_id": "graph.inputs.request_id"},
                        "newsroom.wait",
                        "1",
                        "graph.inputs.tenant_scope_ref",
                        "graph.inputs.identity_scope_ref",
                        timeout_policy=WaitTimeoutPolicy("route", "timeout"),
                        deadline_input_path="graph.inputs.deadline_ref",
                    ),
                    StepRef("normal"),
                    StepRef("timeout"),
                )
            ),
            input_keys=tuple(sorted(inputs)),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        inputs=inputs,
        metadata=dict(base.metadata),
        budget=HarnessBudget.safe_default(),
        created_at=_CREATED_AT,
    )


def _parallel_wait_run_spec(run_id: str) -> HarnessRunSpec:
    base = _wait_run_spec(run_id)
    inputs = dict(base.inputs)
    fast = HarnessStepSpec(
        "fast",
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    wait = Wait(
        "signal-wait",
        "signal",
        {"request_id": "graph.inputs.request_id"},
        "newsroom.wait",
        "1",
        "graph.inputs.tenant_scope_ref",
        "graph.inputs.identity_scope_ref",
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=(fast,),
        entry_step_id="fast",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("wait", wait, "parallel.wait"),
                    ParallelBranch("fast", StepRef("fast"), "parallel.fast"),
                ),
                failure_policy="wait_all",
            ),
            input_keys=tuple(sorted(inputs)),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        inputs=inputs,
        metadata=dict(base.metadata),
        budget=HarnessBudget.safe_default(),
        created_at=_CREATED_AT,
    )


def _scope(run_id: str, registration) -> HarnessWaitScope:
    return HarnessWaitScope(
        registration.wait_id,
        run_id,
        registration.node_instance_id,
        registration.tenant_scope_ref,
        registration.identity_scope_ref,
        registration.signal_schema_ref,
        registration.correlation_ref,
    )


def _registration_ref(state, registration) -> str:
    node = next(
        item
        for item in state.node_instances
        if item.instance_id == registration.node_instance_id
    )
    return node.metadata["wait_registration_ref"]


def _node(state, node_id: str):
    return next(
        item for item in state.node_instances if item.identity.node_id == node_id
    )
