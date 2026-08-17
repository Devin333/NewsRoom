from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_operations import (
    HARNESS_GRAPH_RUN_OPERATION_CONTRACT_ID,
    HARNESS_GRAPH_RUN_OPERATION_CONTRACT_VERSION,
    HARNESS_GRAPH_RUN_OPERATION_NODE_ID,
    HarnessGraphRunOperation,
    HarnessGraphRunOperationType,
)
from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphObservationType,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
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
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.graph.dsl import HarnessGraphSpec, Sequence, StepRef, Wait
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workers.result import HarnessWorkerResult


_NOW = datetime(2026, 8, 15, tzinfo=UTC)
_ACTOR_REF = checksum_for("graph-run-operation-actor")


class _Dispatcher:
    def __init__(self) -> None:
        self.activities: list[HarnessGraphActivity] = []
        self.cancellations: list[object] = []

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        self.activities.append(activity)

    def request_cancellation(self, request: object) -> None:
        self.cancellations.append(request)


def test_graph_cancel_is_durable_before_dispatch_and_waits_for_termination() -> None:
    run_spec = _run_spec("run-operation-cancel")
    port = InMemoryHarnessEventPort()
    dispatcher = _Dispatcher()
    control_plane = _control_plane(port, dispatcher)
    started = control_plane.run(run_spec)
    operation = _cancellation(run_spec.run_id, "cancel-1")

    accepted = control_plane.accept_graph_run_operation(
        run_spec,
        operation,
        occurred_at=_at(1),
    )
    after_accept = control_plane.recover_graph(run_spec)

    assert accepted.accepted_sequence > 0
    assert after_accept.metadata["pending_run_operation"]["operation_ref"] == (
        accepted.operation_ref
    )
    assert dispatcher.cancellations == []
    assert started.graph_state is not None
    assert started.graph_state.active_activities

    pending = control_plane.recover_and_run(run_spec)
    pending_state = pending.graph_state

    assert pending_state is not None
    assert pending_state.lifecycle is RunLifecycle.RUNNING
    assert pending_state.outcome is RunOutcome.NONE
    assert pending_state.node_instances[0].status is (
        HarnessNodeInstanceStatus.CANCEL_REQUESTED
    )
    assert len(dispatcher.cancellations) == 1
    recovery = port.recover_graph(run_spec.run_id)
    cancel_decision = next(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type
        is HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL
    )
    assert cancel_decision.decision.evidence_refs == (accepted.operation_ref,)
    assert any(
        item.cause_checksum == cancel_decision.decision.decision_checksum
        for item in recovery.projection_commits
    )

    activity = dispatcher.activities[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=checksum_for("cancelled-activity-evidence"),
        payload_ref=checksum_for("cancelled-activity-payload"),
        status="cancelled",
        termination_confirmed=True,
    )
    control_plane.accept_graph_activity_result(
        run_spec,
        result,
        occurred_at=_at(2),
    )
    completed = control_plane.recover_and_run(run_spec)
    completed_state = completed.graph_state

    assert completed_state is not None
    assert completed_state.lifecycle is RunLifecycle.COMPLETED
    assert completed_state.outcome is RunOutcome.CANCELLED
    assert "pending_run_operation" not in completed_state.metadata
    verified = control_plane.verify_graph_history(run_spec)
    assert verified.projection_checksum == completed_state.projection_checksum


def test_graph_cancel_retry_is_idempotent_and_conflict_fails_closed() -> None:
    run_spec = _run_spec("run-operation-idempotency")
    port = InMemoryHarnessEventPort()
    dispatcher = _Dispatcher()
    control_plane = _control_plane(port, dispatcher)
    control_plane.run(run_spec)
    operation = _cancellation(run_spec.run_id, "cancel-idempotent")

    first = control_plane.accept_graph_run_operation(
        run_spec,
        operation,
        occurred_at=_at(1),
    )
    retry = control_plane.accept_graph_run_operation(
        run_spec,
        operation,
        occurred_at=_at(2),
    )
    conflicting = HarnessGraphRunOperation(
        HarnessGraphRunOperationType.CANCEL,
        operation.operation_id,
        run_spec.run_id,
        _ACTOR_REF,
        "different_reason",
        0,
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.accept_graph_run_operation(
            run_spec,
            conflicting,
            occurred_at=_at(3),
        )

    assert retry == first
    assert captured.value.code == "graph_run_operation_identity_conflict"
    recovery = port.recover_graph(run_spec.run_id)
    operations = tuple(
        item
        for item in recovery.observation_commits
        if item.observation.observation_type.value == "run_operation"
    )
    assert len(operations) == 1


def test_graph_cancel_before_dispatch_prevents_worker_execution() -> None:
    run_spec = _run_spec("run-operation-before-dispatch")
    worker_calls: list[str] = []
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "operate": lambda _task: (
                worker_calls.append("operate")
                or HarnessWorkerResult("succeeded")
            )
        },
    )
    control_plane.initialize_graph(run_spec)
    operation = _cancellation(run_spec.run_id, "cancel-before-dispatch")

    control_plane.accept_graph_run_operation(
        run_spec,
        operation,
        occurred_at=_at(1),
    )
    result = control_plane.recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert result.graph_state.outcome is RunOutcome.CANCELLED
    assert worker_calls == []
    recovery = control_plane.graph_transition_port.recover_graph(run_spec.run_id)
    assert all(
        item.decision.decision_type
        is not HarnessGraphDecisionType.DISPATCH_ACTIVITY
        for item in recovery.decision_commits
    )


def test_graph_cancel_resolves_wait_registration_and_replays() -> None:
    run_spec = _waiting_run_spec("run-operation-waiting")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(port, _Dispatcher())
    waiting_result = control_plane.run(run_spec)
    operation = _cancellation(run_spec.run_id, "cancel-waiting")

    assert waiting_result.graph_state is not None
    assert waiting_result.graph_state.lifecycle is RunLifecycle.WAITING
    assert waiting_result.graph_state.wait_registrations[0].unresolved

    accepted = control_plane.accept_graph_run_operation(
        run_spec,
        operation,
        occurred_at=_at(1),
    )
    completed = control_plane.recover_and_run(run_spec)

    assert completed.graph_state is not None
    state = completed.graph_state
    assert state.lifecycle is RunLifecycle.COMPLETED
    assert state.outcome is RunOutcome.CANCELLED
    assert state.wait_registrations[0].status is HarnessWaitStatus.CANCELLED
    assert state.wait_registrations[0].resolution_event_ref == accepted.operation_ref
    assert all(item.is_terminal for item in state.node_instances)
    replayed = control_plane.verify_graph_history(run_spec)
    assert replayed.projection_checksum == state.projection_checksum


def test_graph_run_operation_rejects_untyped_observation_boundary() -> None:
    run_spec = _run_spec("run-operation-typed-boundary")
    control_plane = _control_plane(InMemoryHarnessEventPort(), _Dispatcher())
    state = control_plane.initialize_graph(run_spec)
    operation = _cancellation(run_spec.run_id, "cancel-untyped")
    accepted = HarnessGraphRunOperation(
        operation.operation_type,
        operation.operation_id,
        operation.run_id,
        operation.actor_identity_scope_ref,
        operation.reason_code,
        state.last_event_sequence + 1,
    )
    observation = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.RUN_OPERATION,
        HARNESS_GRAPH_RUN_OPERATION_NODE_ID,
        run_spec.run_id,
        0,
        accepted.accepted_sequence,
        HarnessContractReference(
            HarnessContractKind.RUN_OPERATION,
            HARNESS_GRAPH_RUN_OPERATION_CONTRACT_ID,
            HARNESS_GRAPH_RUN_OPERATION_CONTRACT_VERSION,
        ),
        accepted.operation_ref,
        payload={"record": accepted.to_dict()},
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_at(1),
        )

    assert captured.value.code == "graph_run_operation_typed_boundary_required"
    recovery = control_plane.graph_transition_port.recover_graph(run_spec.run_id)
    assert recovery.observation_commits == ()


def test_graph_run_operation_record_rejects_tampered_content() -> None:
    operation = HarnessGraphRunOperation(
        HarnessGraphRunOperationType.CANCEL,
        "cancel-tampered",
        "run-operation-tampered",
        _ACTOR_REF,
        "operator_cancelled",
        7,
    )
    tampered = operation.to_dict()
    tampered["reason_code"] = "forged_reason"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphRunOperation.from_dict(tampered)

    assert captured.value.code == "invalid_graph_run_operation_checksum"


def _control_plane(
    port: InMemoryHarnessEventPort,
    dispatcher: _Dispatcher,
) -> HarnessControlPlane:
    return HarnessControlPlane(
        event_port=port,
        worker_registry={
            "operate": lambda _task: HarnessWorkerResult("succeeded")
        },
        graph_activity_dispatcher=dispatcher,
    )


def _run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec(
                "operate",
                "script",
                metadata={"step_version": "1", "worker_version": "1"},
            ),
        ),
        entry_step_id="operate",
        graph=HarnessGraphSpec(f"graph-{run_id}", StepRef("operate")),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        metadata={
            "tenant_scope_ref": checksum_for(f"tenant-{run_id}"),
            "identity_scope_ref": checksum_for(f"identity-{run_id}"),
            "subject_scope_ref": checksum_for(f"subject-{run_id}"),
        },
        created_at=_NOW,
    )


def _waiting_run_spec(run_id: str) -> HarnessRunSpec:
    tenant_ref = checksum_for(f"tenant-{run_id}")
    identity_ref = checksum_for(f"identity-{run_id}")
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec(
                "operate",
                "script",
                metadata={"step_version": "1", "worker_version": "1"},
            ),
        ),
        entry_step_id="operate",
        graph=HarnessGraphSpec(
            f"graph-{run_id}",
            Sequence(
                (
                    Wait(
                        "operation-wait",
                        "signal",
                        {"request_id": "graph.inputs.request_id"},
                        "newsroom.wait",
                        "1",
                        "graph.inputs.tenant_scope_ref",
                        "graph.inputs.identity_scope_ref",
                    ),
                    StepRef("operate"),
                )
            ),
            input_keys=(
                "identity_scope_ref",
                "request_id",
                "tenant_scope_ref",
            ),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        inputs={
            "identity_scope_ref": identity_ref,
            "request_id": f"request-{run_id}",
            "tenant_scope_ref": tenant_ref,
        },
        metadata={
            "tenant_scope_ref": tenant_ref,
            "identity_scope_ref": identity_ref,
            "subject_scope_ref": checksum_for(f"subject-{run_id}"),
        },
        created_at=_NOW,
    )


def _cancellation(run_id: str, operation_id: str) -> HarnessGraphRunOperation:
    return HarnessGraphRunOperation(
        HarnessGraphRunOperationType.CANCEL,
        operation_id,
        run_id,
        _ACTOR_REF,
        "operator_cancelled",
        0,
    )


def _at(minutes: int) -> datetime:
    return _NOW + timedelta(minutes=minutes)
