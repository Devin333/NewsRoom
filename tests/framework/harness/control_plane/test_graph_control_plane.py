from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from framework.events.errors import EventReplayMismatchError, EventStoreCorruptionError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphActivityCancellationRequest,
)
from framework.harness.graph.decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphObservationType,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphRecovery,
    HarnessGraphTransitionPort,
)
from framework.harness.control_plane.graph_state import (
    HarnessGraphState,
    HarnessNodeInstanceStatus,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.policy import HarnessBudget
from framework.harness.control_plane.scheduler import HarnessScheduler
from framework.harness.control_plane.state import HarnessRunSpec, HarnessStepStatus
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.conditions import ConditionPredicate
from framework.harness.graph.dsl import (
    Choice,
    ChoiceBranch,
    HarnessGraphSpec,
    Sequence,
    StepRef,
)
from framework.harness.graph.model import (
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.graph.validation import HarnessGraphPreflightPolicy
from framework.harness.graph.validation import HarnessGraphPreflight
from framework.harness.workers.result import HarnessWorkerResult


_CREATED_AT = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


def test_explicit_graph_initialization_pins_graph_before_run_creation() -> None:
    run_spec = _run_spec("run-graph-init")
    event_port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port=event_port)

    state = control_plane.initialize(run_spec)
    repeated = control_plane.initialize(run_spec)

    assert isinstance(state, HarnessGraphState)
    assert repeated == state
    assert state.lifecycle is RunLifecycle.CREATED
    assert state.last_event_sequence == 1
    assert (
        state.graph_ref.checksum
        == control_plane._prepared_graphs[run_spec.run_id].checksum
    )
    assert (
        state.metadata["run_spec_checksum"]
        == control_plane._prepared_run_specs[run_spec.run_id]
    )
    assert state.budgets.require("node_activations").limit == 100_000
    assert state.budgets.require("max_active_nodes").limit == 1
    assert event_port.events == []
    assert not hasattr(event_port, "states")
    assert not hasattr(event_port, "transitions")
    recovery = control_plane.graph_transition_port.recover_graph(run_spec.run_id)
    assert recovery.state == state
    assert recovery.graph == control_plane._prepared_graphs[run_spec.run_id]
    assert len(recovery.projection_commits) == 1
    assert recovery.projection_commits[0].commit_kind.value == "initialize"


def test_explicit_graph_run_executes_through_graph_control_plane() -> None:
    run_spec = _run_spec("run-explicit-graph")
    control_plane = _control_plane()

    result = control_plane.run(run_spec)

    assert result.state.status.value == "succeeded"
    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    recovery = control_plane.graph_transition_port.recover_graph(run_spec.run_id)
    assert recovery.state == result.graph_state
    assert recovery.pending_decisions == ()


def test_sequence_run_completes_predecessor_before_activating_successor() -> None:
    run_spec = _run_spec(
        "run-sequence-cutover",
        step_ids=("first", "second"),
    )
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def record_worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("succeeded", output={"step_id": task["step_id"]})

    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "first": record_worker,
            "second": record_worker,
        },
    )

    result = control_plane.run(run_spec)

    assert worker_calls == ["first", "second"]
    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert {
        node.identity.node_id: node.status for node in result.graph_state.node_instances
    } == {
        "first": HarnessNodeInstanceStatus.SUCCEEDED,
        "second": HarnessNodeInstanceStatus.SUCCEEDED,
    }
    recovery = port.recover_graph(run_spec.run_id)
    first_completion = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
        and commit.decision.node_id == "first"
    )
    second_activation = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
        and commit.decision.node_id == "second"
    )
    assert first_completion.sequence < second_activation.sequence


def test_legacy_declaration_run_recover_and_resume_use_only_graph_executor() -> None:
    steps = tuple(
        HarnessStepSpec(
            step_id,
            "script",
            metadata={
                "step_version": "1",
                "worker_version": "1",
                **({"approval_required": True} if step_id == "first" else {}),
            },
        )
        for step_id in ("first", "second")
    )
    run_spec = HarnessRunSpec(
        run_id="run-legacy-declaration-graph-only",
        workflow=HarnessWorkflowSpec(
            workflow_id="legacy-declaration-graph-only",
            steps=steps,
            entry_step_id="first",
            routing_rules=(HarnessRoutingRule("first", "second"),),
        ),
        created_at=_CREATED_AT,
    )
    port = InMemoryHarnessEventPort()
    scheduler = HarnessScheduler()
    worker_calls: list[str] = []

    def record_worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("succeeded", output={"step_id": task["step_id"]})

    control_plane = HarnessControlPlane(
        event_port=port,
        scheduler=scheduler,
        worker_registry={"first": record_worker, "second": record_worker},
    )

    waiting = control_plane.run(run_spec)
    resumed = control_plane.resume_after_approval(waiting.state, approved=True)
    recovered = HarnessControlPlane(
        event_port=port,
        scheduler=scheduler,
        worker_registry={"first": record_worker, "second": record_worker},
    ).recover_and_run(run_spec)

    assert waiting.graph_state is not None
    assert waiting.graph_state.lifecycle is RunLifecycle.WAITING
    assert resumed.graph_state is not None
    assert resumed.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert resumed.graph_state.outcome is RunOutcome.SUCCEEDED
    assert recovered.graph_state == resumed.graph_state
    assert worker_calls == ["first", "second"]
    assert not hasattr(port, "states")
    assert not hasattr(port, "transitions")
    assert all(
        isinstance(decision, HarnessGraphDecision)
        for result in (waiting, resumed, recovered)
        for decision in result.decisions
    )


def test_graph_activation_commits_decision_before_projection() -> None:
    run_spec = _run_spec("run-graph-activation")
    control_plane = _control_plane()
    initial = control_plane.initialize_graph(run_spec)
    decision = control_plane.next_graph_decision(run_spec, initial)

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE

    projected = control_plane.apply_graph_decision(
        run_spec,
        initial,
        decision,
        occurred_at=_at(1),
    )
    recovery = control_plane.graph_transition_port.recover_graph(run_spec.run_id)

    assert projected.lifecycle is RunLifecycle.RUNNING
    assert projected.last_event_sequence == 3
    assert len(projected.node_instances) == 1
    assert projected.node_instances[0].status is HarnessNodeInstanceStatus.READY
    assert projected.budgets.require("node_activations").used == 1
    assert [item.sequence for item in recovery.decision_commits] == [2]
    assert [item.sequence for item in recovery.projection_commits] == [1, 3]
    assert recovery.projection_commits[-1].cause_checksum == decision.decision_checksum
    assert recovery.projection_commits[-1].budget_reservations == {
        "node_activations": 1
    }
    assert recovery.pending_decisions == ()


def test_control_decision_rejects_incompatible_node_kind_before_commit() -> None:
    run_spec = _choice_run_spec("run-control-kind")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port=port)
    ready = _activate_entry(control_plane, run_spec)
    node = ready.node_instances[0]
    invalid = _control_decision(
        ready,
        HarnessGraphDecisionType.OPEN_FORK,
        node_id=node.identity.node_id,
        node_instance_id=node.instance_id,
        target_node_ids=("analyze",),
    )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.apply_graph_decision(
            run_spec,
            ready,
            invalid,
            occurred_at=_at(2),
        )

    assert captured.value.code == "graph_control_node_kind_mismatch"
    assert port.recover_graph(run_spec.run_id) == before


def test_choice_control_decision_applies_only_from_ready_choice() -> None:
    run_spec = _choice_run_spec("run-control-choice")
    control_plane = _control_plane()
    ready = _activate_entry(control_plane, run_spec)
    node = ready.node_instances[0]
    decision = _control_decision(
        ready,
        HarnessGraphDecisionType.SELECT_CHOICE,
        node_id=node.identity.node_id,
        node_instance_id=node.instance_id,
        target_node_ids=("analyze",),
    )

    projected = control_plane.apply_graph_decision(
        run_spec,
        ready,
        decision,
        occurred_at=_at(2),
    )

    assert projected.node_instances[0].status is HarnessNodeInstanceStatus.SUCCEEDED
    assert projected.node_instances[0].last_event_sequence == 5


def test_choice_run_uses_priority_and_commits_selection_before_activation() -> None:
    run_spec = _priority_choice_run_spec("run-choice-priority")
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def record_worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("succeeded", output={"step_id": task["step_id"]})

    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "high": record_worker,
            "low": record_worker,
            "fallback": record_worker,
        },
    )

    result = control_plane.run(run_spec)

    assert worker_calls == ["high"]
    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    recovery = port.recover_graph(run_spec.run_id)
    selection = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE
    )
    target_activation = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
        and commit.decision.node_id == "high"
    )
    assert selection.decision.target_node_ids == ("high",)
    assert selection.sequence < target_activation.sequence
    assert all(
        commit.decision.node_id not in {"low", "fallback"}
        or commit.decision.decision_type
        is not HarnessGraphDecisionType.DISPATCH_ACTIVITY
        for commit in recovery.decision_commits
    )


def test_choice_run_without_match_or_default_halts_before_worker_execution() -> None:
    run_spec = _no_match_choice_run_spec("run-choice-no-match")
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def record_worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("succeeded", output={"step_id": task["step_id"]})

    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"target": record_worker},
    )

    result = control_plane.run(run_spec)

    assert worker_calls == []
    assert result.worker_results == {}
    assert result.state.status.value == "halted"
    assert result.state.metadata["terminal_reason"] == "no_matching_route"
    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.HALTED
    assert result.graph_state.outcome is RunOutcome.NONE
    assert result.graph_state.terminal_reason_code == "no_matching_route"
    recovery = port.recover_graph(run_spec.run_id)
    halt = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.HALT_RUN
    )
    assert halt.decision.reason_code == "no_matching_route"
    assert all(
        commit.decision.decision_type is not HarnessGraphDecisionType.DISPATCH_ACTIVITY
        for commit in recovery.decision_commits
    )


def test_invalid_step_transition_is_rejected_before_durable_commit() -> None:
    run_spec = _run_spec("run-invalid-step-transition")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(
        event_port=port,
        dispatcher=dispatcher,
    )
    ready = _activate_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    node = ready.node_instances[0]
    invalid = _step_decision(
        ready,
        graph,
        node.instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.apply_graph_decision(
            run_spec,
            ready,
            invalid,
            occurred_at=_at(3),
            activity_input_ref=_sha("inputs"),
        )

    assert captured.value.code == "graph_step_decision_state_mismatch"
    after = port.recover_graph(run_spec.run_id)
    assert after.expected_last_sequence == before.expected_last_sequence
    assert after.decision_commits == before.decision_commits
    assert dispatcher.calls == []


def test_step_dispatch_rejects_noncontiguous_attempt_before_commit() -> None:
    run_spec = _run_spec("run-invalid-attempt")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=2,
    )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.apply_graph_decision(
            run_spec,
            planning,
            decision,
            occurred_at=_at(4),
            activity_input_ref=_sha("worker-input"),
        )

    assert captured.value.code == "graph_step_decision_attempt_mismatch"
    assert port.recover_graph(run_spec.run_id) == before
    assert dispatcher.calls == []


def test_step_decision_rejects_undeclared_runtime_binding_before_commit() -> None:
    run_spec = _run_spec("run-invalid-binding")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    valid = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    invalid = replace(
        valid,
        binding_versions={
            **dict(valid.binding_versions),
            "gate:0000": "undeclared-gate@999",
        },
    )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.apply_graph_decision(
            run_spec,
            planning,
            invalid,
            occurred_at=_at(4),
            activity_input_ref=_sha("worker-input"),
        )

    assert captured.value.code == "graph_control_decision_mismatch"
    assert port.recover_graph(run_spec.run_id) == before


def test_transition_port_rejects_unknown_node_before_pending_commit() -> None:
    run_spec = _run_spec("run-port-unknown-node")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port=port)
    initial = control_plane.initialize_graph(run_spec)
    invalid = HarnessGraphDecision(
        HarnessGraphDecisionType.ACTIVATE_NODE,
        run_spec.run_id,
        initial.graph_ref,
        initial.projection_checksum,
        _sha("observations"),
        "unknown_node",
        node_id="missing",
    )

    with pytest.raises(HarnessValidationError) as captured:
        port.commit_graph_decision(
            invalid,
            occurred_at=_at(1),
            expected_last_sequence=1,
        )

    assert captured.value.code == "graph_transition_decision_identity_mismatch"
    assert port.recover_graph(run_spec.run_id).decision_commits == ()


def test_stale_projection_checksum_is_rejected_before_decision_commit() -> None:
    run_spec = _run_spec("run-stale-decision")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port=port)
    initial = control_plane.initialize_graph(run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    valid = _activation_decision(initial, graph, "analyze")
    stale = HarnessGraphDecision(
        valid.decision_type,
        valid.run_id,
        valid.graph_ref,
        _sha("stale-projection"),
        valid.observation_checksum,
        valid.reason_code,
        node_id=valid.node_id,
        binding_versions=valid.binding_versions,
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.apply_graph_decision(
            run_spec,
            initial,
            stale,
            occurred_at=_at(1),
        )

    assert captured.value.code == "graph_control_decision_mismatch"
    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.expected_last_sequence == 1
    assert recovery.decision_commits == ()


def test_duplicate_decision_after_later_projection_returns_current_state() -> None:
    run_spec = _run_spec("run-duplicate-current")
    control_plane = _control_plane()
    initial = control_plane.initialize_graph(run_spec)
    activation = control_plane.next_graph_decision(run_spec, initial)
    assert activation is not None
    ready = control_plane.apply_graph_decision(
        run_spec,
        initial,
        activation,
        occurred_at=_at(1),
    )
    graph = control_plane._prepared_graphs[run_spec.run_id]
    enter_plan = _step_decision(
        ready,
        graph,
        ready.node_instances[0].instance_id,
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        attempt=0,
    )
    planning = control_plane.apply_graph_decision(
        run_spec,
        ready,
        enter_plan,
        occurred_at=_at(2),
    )

    repeated = control_plane.apply_graph_decision(
        run_spec,
        initial,
        activation,
        occurred_at=_at(3),
    )

    assert repeated == planning


def test_new_control_plane_rejects_changed_run_scope_before_commit() -> None:
    run_spec = _run_spec("run-scope-restart")
    port = InMemoryHarnessEventPort()
    original = _control_plane(event_port=port)
    initial = original.initialize_graph(run_spec)
    decision = original.next_graph_decision(run_spec, initial)
    assert decision is not None
    changed = HarnessRunSpec(
        run_id=run_spec.run_id,
        workflow=run_spec.workflow,
        budget=run_spec.budget,
        metadata={
            **dict(run_spec.metadata),
            "tenant_scope_ref": _sha("changed-tenant"),
        },
        created_at=run_spec.created_at,
    )
    restarted = _control_plane(event_port=port)
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        restarted.apply_graph_decision(
            changed,
            initial,
            decision,
            occurred_at=_at(1),
        )

    assert captured.value.code == "graph_control_run_spec_mismatch"
    assert port.recover_graph(run_spec.run_id) == before


def test_dispatch_occurs_only_after_causal_projection_commits() -> None:
    run_spec = _run_spec("run-dispatch-order")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port, assert_committed=True)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    node = planning.node_instances[0]
    decision = _step_decision(
        planning,
        graph,
        node.instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )

    running = control_plane.apply_graph_decision(
        run_spec,
        planning,
        decision,
        occurred_at=_at(4),
        activity_input_ref=_sha("worker-input"),
    )

    assert len(dispatcher.calls) == 1
    activity = dispatcher.calls[0]
    assert running.last_event_sequence == activity.causal_decision_sequence + 1
    assert running.node_instances[0].attempt == 1
    assert running.node_instances[0].step_status is HarnessStepStatus.RUNNING
    assert running.active_activities[0].activity_id == activity.activity_id
    assert running.active_activities[0].idempotency_key == activity.idempotency_key
    assert running.active_activities[0].fencing_generation == 1
    assert activity.activity_ref == _definition(graph, "analyze").activity_ref
    assert activity.worker_ref == _definition(graph, "analyze").worker_ref
    assert port.recover_graph(run_spec.run_id).dispatched_activity_ids == frozenset(
        {activity.activity_id}
    )


def test_duplicate_dispatch_rejects_conflicting_input_reference() -> None:
    run_spec = _run_spec("run-dispatch-conflict")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    running = control_plane.apply_graph_decision(
        run_spec,
        planning,
        decision,
        occurred_at=_at(4),
        activity_input_ref=_sha("first-input"),
    )

    with pytest.raises(EventStoreCorruptionError):
        control_plane.apply_graph_decision(
            run_spec,
            planning,
            decision,
            occurred_at=_at(5),
            activity_input_ref=_sha("conflicting-input"),
        )

    assert port.recover_graph(run_spec.run_id).state == running
    assert len(dispatcher.calls) == 1


def test_async_activity_result_is_identity_bound_and_duplicate_idempotent() -> None:
    run_spec = _run_spec("run-result-identity")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("result-evidence"),
        payload_ref=_sha("result-payload"),
        status="succeeded",
    )

    projected = control_plane.accept_graph_activity_result(
        run_spec,
        result,
        occurred_at=_at(5),
    )
    duplicate = control_plane.accept_graph_activity_result(
        run_spec,
        result,
        occurred_at=_at(6),
    )

    assert duplicate == projected
    assert projected.active_activities == ()
    node = projected.node_instances[0]
    assert node.status is HarnessNodeInstanceStatus.RUNNING
    assert node.step_status is HarnessStepStatus.RUNNING
    assert node.evidence_refs[-1].evidence_ref == result.evidence_ref
    assert node.evidence_refs[-1].payload_ref == result.payload_ref
    assert node.evidence_refs[-1].attempt == activity.attempt
    recovery = port.recover_graph(run_spec.run_id)
    assert len(recovery.activity_result_commits) == 1
    assert recovery.pending_activity_results == ()
    assert projected.last_event_sequence == recovery.expected_last_sequence
    assert running.projection_checksum != projected.projection_checksum


def test_graph_observation_duplicate_identical_is_durably_idempotent() -> None:
    run_spec = _run_spec("run-observation-duplicate")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    observation = _worker_status_observation(running, graph)

    projected = control_plane.accept_graph_observation(
        run_spec,
        observation,
        occurred_at=_at(5),
    )
    duplicate = control_plane.accept_graph_observation(
        run_spec,
        observation,
        occurred_at=_at(6),
    )

    assert duplicate == projected
    recovery = port.recover_graph(run_spec.run_id)
    assert len(recovery.observation_commits) == 1
    assert recovery.observation_commits[0].observation == observation
    assert recovery.pending_observations == ()
    observation_projections = tuple(
        item
        for item in recovery.projection_commits
        if item.commit_kind.value == "observation_projection"
    )
    assert len(observation_projections) == 1
    node = projected.node_instances[0]
    assert [
        item.evidence_ref
        for item in node.evidence_refs
        if item.evidence_ref == observation.evidence_ref
    ] == [observation.evidence_ref]
    assert len(node.metadata["accepted_observations"]) == 1


def test_graph_observation_conflicting_duplicate_is_rejected_without_history_change() -> (
    None
):
    run_spec = _run_spec("run-observation-conflict")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    accepted = _worker_status_observation(running, graph)
    projected = control_plane.accept_graph_observation(
        run_spec,
        accepted,
        occurred_at=_at(5),
    )
    conflicting = replace(
        accepted,
        evidence_ref=_sha("conflicting-worker-status"),
        payload={"status": "failed"},
    )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(EventReplayMismatchError, match="stale projection"):
        control_plane.accept_graph_observation(
            run_spec,
            conflicting,
            occurred_at=_at(6),
        )

    after = port.recover_graph(run_spec.run_id)
    assert after == before
    assert after.state == projected
    assert [item.observation for item in after.observation_commits] == [accepted]


@pytest.mark.parametrize(
    ("mutation", "expected_exception", "expected_code"),
    (
        ("stale", EventReplayMismatchError, None),
        ("cross_node", HarnessValidationError, "graph_observation_identity_mismatch"),
        (
            "cross_attempt",
            HarnessValidationError,
            "graph_observation_identity_mismatch",
        ),
    ),
)
def test_graph_observation_rejects_stale_cross_node_and_cross_attempt_inputs(
    mutation: str,
    expected_exception: type[Exception],
    expected_code: str | None,
) -> None:
    run_spec = _run_spec(
        f"run-observation-{mutation}",
        step_ids=("first", "second"),
    )
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    observation = _worker_status_observation(running, graph)
    if mutation == "stale":
        observation = replace(
            observation,
            event_sequence=running.last_event_sequence,
        )
    elif mutation == "cross_node":
        observation = replace(
            observation,
            node_id="second",
            contract_ref=_definition(graph, "second").worker_ref,
        )
    else:
        observation = replace(
            observation, attempt=running.node_instances[0].attempt + 1
        )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(expected_exception) as captured:
        control_plane.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_at(5),
        )

    if expected_code is not None:
        assert captured.value.code == expected_code
    assert port.recover_graph(run_spec.run_id) == before


def test_unconfirmed_cancellation_halts_indeterminate_without_releasing_activity() -> (
    None
):
    run_spec = _run_spec("run-result-unconfirmed-cancel")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("cancel-evidence"),
        payload_ref=_sha("cancel-payload"),
        status="cancelled",
        termination_confirmed=False,
    )

    halted = control_plane.accept_graph_activity_result(
        run_spec,
        result,
        occurred_at=_at(5),
    )
    recovered = control_plane.recover_graph(run_spec)

    assert halted.lifecycle is RunLifecycle.HALTED
    assert halted.outcome is RunOutcome.INDETERMINATE
    assert result.termination_confirmed is False
    assert halted.node_instances[0].status is HarnessNodeInstanceStatus.HALTED
    assert halted.active_activities[0].activity_id == activity.activity_id
    assert recovered == halted
    assert len(dispatcher.calls) == 1
    assert control_plane.next_graph_decision(run_spec, halted) is None


def test_confirmed_cancellation_releases_activity_and_terminalizes_node() -> None:
    run_spec = _run_spec("run-result-confirmed-cancel")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("confirmed-cancel-evidence"),
        payload_ref=_sha("confirmed-cancel-payload"),
        status="cancelled",
        termination_confirmed=True,
    )

    cancelled = control_plane.accept_graph_activity_result(
        run_spec,
        result,
        occurred_at=_at(5),
    )

    assert cancelled.lifecycle is RunLifecycle.RUNNING
    assert cancelled.outcome is RunOutcome.NONE
    assert cancelled.node_instances[0].status is HarnessNodeInstanceStatus.CANCELLED
    assert cancelled.active_activities == ()
    assert control_plane.recover_graph(run_spec) == cancelled


@pytest.mark.parametrize("result_status", ("succeeded", "failed"))
def test_cancel_requested_activity_completion_reconciles_as_cancelled(
    result_status: str,
) -> None:
    run_spec = _run_spec(f"run-cancel-race-{result_status}")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    node = running.node_instances[0]
    activity = dispatcher.calls[0]
    graph = control_plane._prepared_graphs[run_spec.run_id]
    cancel = _control_decision(
        running,
        HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
        node_id=node.identity.node_id,
        node_instance_id=node.instance_id,
        binding_versions=_bindings(_definition(graph, node.identity.node_id)),
    )

    cancelling = control_plane.apply_graph_decision(
        run_spec,
        running,
        cancel,
        occurred_at=_at(5),
    )

    assert cancelling.node_instances[0].status is (
        HarnessNodeInstanceStatus.CANCEL_REQUESTED
    )
    assert len(dispatcher.cancellation_calls) == 1
    request = dispatcher.cancellation_calls[0]
    assert request.activity_id == activity.activity_id
    assert request.attempt == activity.attempt
    assert request.fencing_generation == activity.fencing_generation
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha(f"cancel-race-{result_status}-evidence"),
        payload_ref=_sha(f"cancel-race-{result_status}-payload"),
        status=result_status,
        termination_confirmed=True,
    )

    reconciled = control_plane.accept_graph_activity_result(
        run_spec,
        result,
        occurred_at=_at(6),
    )

    cancelled_node = reconciled.node_instances[0]
    assert cancelled_node.status is HarnessNodeInstanceStatus.CANCELLED
    assert cancelled_node.step_status is HarnessStepStatus.HALTED
    assert cancelled_node.metadata["cancel_reconciliation_status"] == result_status
    assert reconciled.active_activities == ()


def test_cancel_delivery_failure_recovers_same_durable_request() -> None:
    run_spec = _run_spec("run-cancel-delivery-recovery")
    port = InMemoryHarnessEventPort()
    dispatcher = _FailOnceCancellationDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    node = running.node_instances[0]
    graph = control_plane._prepared_graphs[run_spec.run_id]
    cancel = _control_decision(
        running,
        HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
        node_id=node.identity.node_id,
        node_instance_id=node.instance_id,
        binding_versions=_bindings(_definition(graph, node.identity.node_id)),
    )

    with pytest.raises(RuntimeError, match="cancellation unavailable"):
        control_plane.apply_graph_decision(
            run_spec,
            running,
            cancel,
            occurred_at=_at(5),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    assert interrupted.pending_decisions == ()
    assert interrupted.state is not None
    assert interrupted.state.node_instances[0].status is (
        HarnessNodeInstanceStatus.CANCEL_REQUESTED
    )

    recovered = control_plane.recover_graph(run_spec)

    assert recovered.node_instances[0].status is (
        HarnessNodeInstanceStatus.CANCEL_REQUESTED
    )
    assert len(dispatcher.cancellation_attempts) == 2
    assert (
        dispatcher.cancellation_attempts[0].request_checksum
        == dispatcher.cancellation_attempts[1].request_checksum
    )
    assert dispatcher.cancellation_calls == [dispatcher.cancellation_attempts[1]]


@pytest.mark.parametrize("result_status", ("failed", "timeout"))
def test_confirmed_failed_activity_can_retry_with_new_attempt_and_prior_evidence(
    result_status: str,
) -> None:
    run_spec = _run_spec(f"run-result-retry-{result_status}")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, run_spec)
    first_activity = dispatcher.calls[0]
    failed = HarnessGraphActivityResult.for_activity(
        first_activity,
        evidence_ref=_sha(f"{result_status}-evidence"),
        payload_ref=_sha(f"{result_status}-payload"),
        status=result_status,
        termination_confirmed=True,
    )
    failed_state = control_plane.accept_graph_activity_result(
        run_spec,
        failed,
        occurred_at=_at(5),
    )
    graph = control_plane._prepared_graphs[run_spec.run_id]
    retry = _step_decision(
        failed_state,
        graph,
        failed_state.node_instances[0].instance_id,
        HarnessGraphDecisionType.RETRY_NODE,
        attempt=1,
    )
    retrying = control_plane.apply_graph_decision(
        run_spec,
        failed_state,
        retry,
        occurred_at=_at(6),
    )
    redispatch = _step_decision(
        retrying,
        graph,
        retrying.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=2,
    )

    running = control_plane.apply_graph_decision(
        run_spec,
        retrying,
        redispatch,
        occurred_at=_at(7),
        activity_input_ref=_sha("worker-input"),
    )

    assert running.node_instances[0].attempt == 2
    assert running.node_instances[0].evidence_refs[-1].attempt == 1
    assert [item.attempt for item in dispatcher.calls] == [1, 2]
    assert dispatcher.calls[0].activity_id != dispatcher.calls[1].activity_id
    assert dispatcher.calls[0].idempotency_key == dispatcher.calls[1].idempotency_key
    assert [item.fencing_generation for item in dispatcher.calls] == [1, 2]


@pytest.mark.parametrize(
    "mismatch",
    (
        "node_instance_id",
        "attempt",
        "idempotency_key",
        "fencing_generation",
        "tenant_scope_ref",
        "identity_scope_ref",
        "subject_scope_ref",
    ),
)
def test_async_activity_result_rejects_cross_identity_and_scope(
    mismatch: str,
) -> None:
    run_spec = _run_spec(f"run-result-{mismatch}")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    values = {
        "activity_id": activity.activity_id,
        "node_instance_id": activity.node_instance_id,
        "attempt": activity.attempt,
        "idempotency_key": activity.idempotency_key,
        "fencing_generation": activity.fencing_generation,
        "activity_ref": activity.activity_ref,
        "evidence_ref": _sha("result-evidence"),
        "payload_ref": _sha("result-payload"),
        "status": "succeeded",
        "tenant_scope_ref": activity.tenant_scope_ref,
        "identity_scope_ref": activity.identity_scope_ref,
        "subject_scope_ref": activity.subject_scope_ref,
    }
    values[mismatch] = {
        "node_instance_id": "other-node-instance",
        "attempt": activity.attempt + 1,
        "idempotency_key": "other-idempotency-key",
        "fencing_generation": activity.fencing_generation + 1,
        "tenant_scope_ref": _sha("other-tenant"),
        "identity_scope_ref": _sha("other-identity"),
        "subject_scope_ref": _sha("other-subject"),
    }[mismatch]
    result = HarnessGraphActivityResult(**values)

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.accept_graph_activity_result(
            run_spec,
            result,
            occurred_at=_at(5),
        )

    assert captured.value.code == "graph_activity_result_identity_mismatch"
    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.state == running
    assert recovery.activity_result_commits == ()


def test_conflicting_duplicate_activity_result_is_rejected() -> None:
    run_spec = _run_spec("run-result-conflict")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    first = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("first-evidence"),
        payload_ref=_sha("first-payload"),
        status="succeeded",
    )
    conflicting = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("conflicting-evidence"),
        payload_ref=_sha("conflicting-payload"),
        status="failed",
        termination_confirmed=True,
    )
    control_plane.accept_graph_activity_result(
        run_spec,
        first,
        occurred_at=_at(5),
    )

    with pytest.raises(EventReplayMismatchError):
        control_plane.accept_graph_activity_result(
            run_spec,
            conflicting,
            occurred_at=_at(6),
        )


def test_activity_result_for_another_run_is_rejected_before_commit() -> None:
    first_run = _run_spec("run-result-owner")
    other_run = _run_spec("run-result-other")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, first_run)
    control_plane.initialize_graph(other_run)
    activity = dispatcher.calls[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("result-evidence"),
        payload_ref=_sha("result-payload"),
        status="succeeded",
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.accept_graph_activity_result(
            other_run,
            result,
            occurred_at=_at(5),
        )

    assert captured.value.code == "graph_activity_result_run_mismatch"
    assert port.recover_graph(first_run.run_id).activity_result_commits == ()
    assert port.recover_graph(other_run.run_id).activity_result_commits == ()


def test_stale_parallel_activation_cannot_overspend_shared_budget() -> None:
    run_spec = _run_spec("run-budget-cas", step_ids=("first", "second"))
    policy = HarnessGraphPreflightPolicy(
        max_node_activations=2,
        max_active_nodes=2,
        max_parallelism=1,
    )
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port=port, policy=policy)
    initial = control_plane.initialize_graph(run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    first = _activation_decision(initial, graph, "first")
    stale_second = _activation_decision(initial, graph, "second")

    after_first = control_plane.apply_graph_decision(
        run_spec,
        initial,
        first,
        occurred_at=_at(1),
    )
    fresh_second = _activation_decision(after_first, graph, "second")
    after_second = control_plane.apply_graph_decision(
        run_spec,
        after_first,
        fresh_second,
        occurred_at=_at(2),
    )

    with pytest.raises(EventReplayMismatchError):
        control_plane.apply_graph_decision(
            run_spec,
            initial,
            stale_second,
            occurred_at=_at(3),
        )

    assert after_second.budgets.require("node_activations").used == 2
    assert len(after_second.node_instances) == 2
    assert len(port.recover_graph(run_spec.run_id).decision_commits) == 2


def test_shared_worker_call_budget_allows_only_one_competing_dispatch() -> None:
    run_spec = _run_spec(
        "run-worker-budget-cas",
        step_ids=("first", "second"),
        budget=HarnessBudget(
            max_turns=10,
            max_replans=2,
            max_retries_per_step=2,
            max_worker_calls=1,
        ),
    )
    policy = HarnessGraphPreflightPolicy(
        max_node_activations=2,
        max_active_nodes=2,
        max_parallelism=2,
    )
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(
        event_port=port,
        dispatcher=dispatcher,
        policy=policy,
    )
    initial = control_plane.initialize_graph(run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    first_activation = _activation_decision(initial, graph, "first")
    after_first = control_plane.apply_graph_decision(
        run_spec,
        initial,
        first_activation,
        occurred_at=_at(1),
    )
    second_activation = _activation_decision(after_first, graph, "second")
    after_second = control_plane.apply_graph_decision(
        run_spec,
        after_first,
        second_activation,
        occurred_at=_at(2),
    )
    first_node = next(
        item for item in after_second.node_instances if item.identity.node_id == "first"
    )
    second_node = next(
        item
        for item in after_second.node_instances
        if item.identity.node_id == "second"
    )
    first_plan = _step_decision(
        after_second,
        graph,
        first_node.instance_id,
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        attempt=0,
    )
    after_first_plan = control_plane.apply_graph_decision(
        run_spec,
        after_second,
        first_plan,
        occurred_at=_at(3),
    )
    second_plan = _step_decision(
        after_first_plan,
        graph,
        second_node.instance_id,
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        attempt=0,
    )
    planning = control_plane.apply_graph_decision(
        run_spec,
        after_first_plan,
        second_plan,
        occurred_at=_at(4),
    )
    first_dispatch = _step_decision(
        planning,
        graph,
        first_node.instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    after_first_dispatch = control_plane.apply_graph_decision(
        run_spec,
        planning,
        first_dispatch,
        occurred_at=_at(5),
        activity_input_ref=_sha("first-input"),
    )
    second_dispatch = _step_decision(
        after_first_dispatch,
        graph,
        second_node.instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    before = port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.apply_graph_decision(
            run_spec,
            after_first_dispatch,
            second_dispatch,
            occurred_at=_at(6),
            activity_input_ref=_sha("second-input"),
        )

    assert captured.value.code == "graph_budget_exhausted"
    assert (
        port.recover_graph(run_spec.run_id).expected_last_sequence
        == before.expected_last_sequence
    )
    assert [item.node_instance_id for item in dispatcher.calls] == [
        first_node.instance_id
    ]


def test_committed_unprojected_decision_recovers_without_scheduler() -> None:
    run_spec = _run_spec("run-recover-decision")
    port = _FaultInjectingEventPort()
    control_plane = _control_plane(event_port=port)
    initial = control_plane.initialize_graph(run_spec)
    decision = control_plane.next_graph_decision(run_spec, initial)
    assert decision is not None
    port.fail_next_projection = True

    with pytest.raises(RuntimeError, match="projection unavailable"):
        control_plane.apply_graph_decision(
            run_spec,
            initial,
            decision,
            occurred_at=_at(1),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    assert interrupted.state == initial
    assert len(interrupted.pending_decisions) == 1

    recovered = control_plane.recover_graph(run_spec)

    assert recovered.last_event_sequence == 3
    assert recovered.node_instances[0].status is HarnessNodeInstanceStatus.READY
    assert port.recover_graph(run_spec.run_id).pending_decisions == ()


def test_projection_store_failure_commits_no_activity_dispatch_until_recovery() -> None:
    run_spec = _run_spec("run-projection-failure")
    port = _FaultInjectingEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    port.fail_next_projection = True

    with pytest.raises(RuntimeError, match="projection unavailable"):
        control_plane.apply_graph_decision(
            run_spec,
            planning,
            decision,
            occurred_at=_at(4),
            activity_input_ref=_sha("worker-input"),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    assert interrupted.state == planning
    assert len(interrupted.pending_decisions) == 1
    assert interrupted.activities == ()
    assert dispatcher.calls == []

    recovered = control_plane.recover_graph(run_spec)
    assert len(recovered.active_activities) == 1
    assert len(dispatcher.calls) == 1


def test_activity_result_store_failure_preserves_active_projection() -> None:
    run_spec = _run_spec("run-activity-result-failure")
    port = _FaultInjectingEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("result-evidence"),
        payload_ref=_sha("result-payload"),
        status="succeeded",
    )
    port.fail_next_activity_result = True

    with pytest.raises(RuntimeError, match="activity result store unavailable"):
        control_plane.accept_graph_activity_result(
            run_spec,
            result,
            occurred_at=_at(5),
        )

    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.state == running
    assert recovery.activity_result_commits == ()
    assert recovery.pending_activity_results == ()


def test_dispatch_failure_recovers_same_committed_activity_identity() -> None:
    run_spec = _run_spec("run-recover-dispatch")
    port = InMemoryHarnessEventPort()
    dispatcher = _FailOnceDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )

    with pytest.raises(RuntimeError, match="dispatch unavailable"):
        control_plane.apply_graph_decision(
            run_spec,
            planning,
            decision,
            occurred_at=_at(4),
            activity_input_ref=_sha("worker-input"),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    assert len(interrupted.state.active_activities) == 1
    assert interrupted.dispatched_activity_ids == frozenset()
    committed_activity = interrupted.activities[0]

    recovered = control_plane.recover_graph(run_spec)

    assert recovered.active_activities[0].activity_id == committed_activity.activity_id
    assert [item.activity_id for item in dispatcher.calls] == [
        committed_activity.activity_id,
        committed_activity.activity_id,
    ]
    assert port.recover_graph(run_spec.run_id).dispatched_activity_ids == frozenset(
        {committed_activity.activity_id}
    )


def test_committed_activity_result_recovers_without_redispatch() -> None:
    run_spec = _run_spec("run-recover-result")
    port = _FaultInjectingEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, run_spec)
    activity = dispatcher.calls[0]
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=_sha("result-evidence"),
        payload_ref=_sha("result-payload"),
        status="succeeded",
    )
    port.fail_next_projection = True

    with pytest.raises(RuntimeError, match="projection unavailable"):
        control_plane.accept_graph_activity_result(
            run_spec,
            result,
            occurred_at=_at(5),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    assert len(interrupted.pending_activity_results) == 1
    assert len(interrupted.state.active_activities) == 1

    recovered = control_plane.recover_graph(run_spec)

    assert recovered.active_activities == ()
    assert (
        recovered.node_instances[0].evidence_refs[-1].evidence_ref
        == result.evidence_ref
    )
    assert len(dispatcher.calls) == 1


def test_committed_unprojected_observation_recovers_exactly_once() -> None:
    run_spec = _run_spec("run-recover-observation")
    port = _FaultInjectingEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    observation = _worker_status_observation(running, graph)
    port.fail_next_projection = True

    with pytest.raises(RuntimeError, match="projection unavailable"):
        control_plane.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_at(5),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    assert interrupted.state == running
    assert interrupted.expected_last_sequence == running.last_event_sequence + 1
    assert [item.observation for item in interrupted.pending_observations] == [
        observation
    ]
    assert all(
        item.evidence_ref != observation.evidence_ref
        for item in interrupted.state.node_instances[0].evidence_refs
    )

    recovered = control_plane.recover_graph(run_spec)
    replayed = control_plane.accept_graph_observation(
        run_spec,
        observation,
        occurred_at=_at(6),
    )

    assert replayed == recovered
    assert recovered.last_event_sequence == running.last_event_sequence + 2
    assert [
        item.evidence_ref
        for item in recovered.node_instances[0].evidence_refs
        if item.evidence_ref == observation.evidence_ref
    ] == [observation.evidence_ref]
    recovery = port.recover_graph(run_spec.run_id)
    assert len(recovery.observation_commits) == 1
    assert recovery.pending_observations == ()
    assert (
        len(
            tuple(
                item
                for item in recovery.projection_commits
                if item.cause_checksum == observation.observation_checksum
            )
        )
        == 1
    )
    assert len(dispatcher.calls) == 1


def test_observation_projection_failure_fails_closed_until_recovery() -> None:
    run_spec = _run_spec("run-observation-projection-fail-closed")
    port = _FaultInjectingEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    running = _dispatch_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    committed = _worker_status_observation(running, graph)
    port.fail_next_projection = True

    with pytest.raises(RuntimeError, match="projection unavailable"):
        control_plane.accept_graph_observation(
            run_spec,
            committed,
            occurred_at=_at(5),
        )

    interrupted = port.recover_graph(run_spec.run_id)
    competing = replace(
        committed,
        event_sequence=interrupted.expected_last_sequence + 1,
        evidence_ref=_sha("competing-worker-status"),
        payload={"status": "failed"},
    )
    with pytest.raises(HarnessValidationError) as captured:
        control_plane.accept_graph_observation(
            run_spec,
            competing,
            occurred_at=_at(6),
        )

    assert captured.value.code == "graph_recovery_required"
    after = port.recover_graph(run_spec.run_id)
    assert after == interrupted
    assert after.state == running
    assert [item.observation for item in after.pending_observations] == [committed]
    assert after.state.projection_checksum == running.projection_checksum
    assert len(dispatcher.calls) == 1


def test_event_store_failure_prevents_projection_and_activity_dispatch() -> None:
    run_spec = _run_spec("run-fail-closed")
    port = _FaultInjectingEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    before = port.recover_graph(run_spec.run_id)
    port.fail_next_decision = True

    with pytest.raises(RuntimeError, match="decision store unavailable"):
        control_plane.apply_graph_decision(
            run_spec,
            planning,
            decision,
            occurred_at=_at(4),
            activity_input_ref=_sha("worker-input"),
        )

    after = port.recover_graph(run_spec.run_id)
    assert after.state == before.state
    assert after.expected_last_sequence == before.expected_last_sequence
    assert after.pending_decisions == ()
    assert dispatcher.calls == []


def test_recovery_allows_non_graph_canonical_sequence_gaps() -> None:
    run_spec = _run_spec("run-recovery-gap")
    port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port=port)
    control_plane.initialize_graph(run_spec)
    recovery = port.recover_graph(run_spec.run_id)

    with_gap = HarnessGraphRecovery(
        run_id=recovery.run_id,
        graph=recovery.graph,
        run_spec_checksum=recovery.run_spec_checksum,
        state=recovery.state,
        expected_last_sequence=2,
        decision_commits=recovery.decision_commits,
        projection_commits=recovery.projection_commits,
        activity_result_commits=recovery.activity_result_commits,
        activities=recovery.activities,
        dispatched_activity_ids=recovery.dispatched_activity_ids,
    )

    assert with_gap.expected_last_sequence == 2
    assert with_gap.state is not None
    assert with_gap.state.last_event_sequence == 1
    with pytest.raises(EventStoreCorruptionError):
        replace(with_gap, expected_last_sequence=0)


def test_projection_rejects_activity_worker_binding_tamper() -> None:
    run_spec = _run_spec("run-recovery-binding")
    port = InMemoryHarnessEventPort()
    dispatcher = _RecordingDispatcher(port)
    control_plane = _control_plane(event_port=port, dispatcher=dispatcher)
    _dispatch_entry(control_plane, run_spec)
    recovery = port.recover_graph(run_spec.run_id)
    activity = recovery.activities[0]
    tampered_activity = replace(
        activity,
        worker_ref=replace(activity.worker_ref, version="2"),
    )
    activity_projection = next(
        item for item in recovery.projection_commits if item.activity is not None
    )

    with pytest.raises(HarnessValidationError) as captured:
        replace(activity_projection, activity=tampered_activity)

    assert captured.value.code == "graph_projection_activity_mismatch"


def test_failed_graph_initialization_does_not_poison_run_id() -> None:
    run_spec = _run_spec("run-init-failure")
    port = _FaultInjectingEventPort()
    port.fail_next_initialization = True
    control_plane = _control_plane(event_port=port)

    with pytest.raises(RuntimeError, match="initialization store unavailable"):
        control_plane.initialize_graph(run_spec)

    assert port.recover_graph(run_spec.run_id).state is None
    assert run_spec.run_id not in control_plane._prepared_run_specs
    assert run_spec.run_id not in control_plane._prepared_graphs

    state = control_plane.initialize_graph(run_spec)

    assert state.lifecycle is RunLifecycle.CREATED


def _control_plane(
    *,
    event_port: InMemoryHarnessEventPort | None = None,
    dispatcher=None,
    policy: HarnessGraphPreflightPolicy | None = None,
) -> HarnessControlPlane:
    return HarnessControlPlane(
        event_port=event_port or InMemoryHarnessEventPort(),
        worker_registry={
            "first": _worker,
            "second": _worker,
            "analyze": _worker,
        },
        graph_activity_dispatcher=dispatcher,
        graph_preflight=HarnessGraphPreflight(policy=policy),
    )


def _run_spec(
    run_id: str,
    *,
    step_ids: tuple[str, ...] = ("analyze",),
    budget: HarnessBudget | None = None,
) -> HarnessRunSpec:
    steps = tuple(
        HarnessStepSpec(
            step_id,
            "script",
            metadata={"step_version": "1", "worker_version": "1"},
        )
        for step_id in step_ids
    )
    root = (
        StepRef(step_ids[0])
        if len(step_ids) == 1
        else Sequence(tuple(StepRef(step_id) for step_id in step_ids))
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=steps,
        entry_step_id=step_ids[0],
        graph=HarnessGraphSpec(graph_id=f"graph-{run_id}", root=root),
    )
    return HarnessRunSpec(
        run_id=run_id,
        workflow=workflow,
        budget=budget or HarnessBudget.safe_default(),
        metadata={
            "tenant_scope_ref": _sha(f"tenant-{run_id}"),
            "identity_scope_ref": _sha(f"identity-{run_id}"),
            "subject_scope_ref": _sha(f"subject-{run_id}"),
        },
        created_at=_CREATED_AT,
    )


def _choice_run_spec(run_id: str) -> HarnessRunSpec:
    step = HarnessStepSpec(
        "analyze",
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=(step,),
        entry_step_id="analyze",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Choice(
                "choose",
                (
                    ChoiceBranch(
                        "default",
                        StepRef("analyze"),
                        priority=0,
                        is_default=True,
                    ),
                ),
            ),
        ),
    )
    return HarnessRunSpec(
        run_id=run_id,
        workflow=workflow,
        metadata={
            "tenant_scope_ref": _sha(f"tenant-{run_id}"),
            "identity_scope_ref": _sha(f"identity-{run_id}"),
            "subject_scope_ref": _sha(f"subject-{run_id}"),
        },
        created_at=_CREATED_AT,
    )


def _priority_choice_run_spec(run_id: str) -> HarnessRunSpec:
    matching = ConditionPredicate("graph.inputs.route", "equals", "matched")
    steps = tuple(
        HarnessStepSpec(
            step_id,
            "script",
            metadata={"step_version": "1", "worker_version": "1"},
        )
        for step_id in ("high", "low", "fallback")
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=steps,
        entry_step_id="high",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Choice(
                "choose",
                (
                    ChoiceBranch(
                        "low-priority",
                        StepRef("low"),
                        priority=20,
                        condition=matching,
                    ),
                    ChoiceBranch(
                        "high-priority",
                        StepRef("high"),
                        priority=10,
                        condition=matching,
                    ),
                    ChoiceBranch(
                        "default",
                        StepRef("fallback"),
                        priority=30,
                        is_default=True,
                    ),
                ),
            ),
        ),
    )
    return HarnessRunSpec(
        run_id=run_id,
        workflow=workflow,
        inputs={"route": "matched"},
        metadata={
            "tenant_scope_ref": _sha(f"tenant-{run_id}"),
            "identity_scope_ref": _sha(f"identity-{run_id}"),
            "subject_scope_ref": _sha(f"subject-{run_id}"),
        },
        created_at=_CREATED_AT,
    )


def _no_match_choice_run_spec(run_id: str) -> HarnessRunSpec:
    step = HarnessStepSpec(
        "target",
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=(step,),
        entry_step_id="target",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Choice(
                "choose",
                (
                    ChoiceBranch(
                        "only",
                        StepRef("target"),
                        priority=0,
                        condition=ConditionPredicate(
                            "graph.inputs.allowed",
                            "equals",
                            True,
                        ),
                    ),
                ),
            ),
        ),
    )
    return HarnessRunSpec(
        run_id=run_id,
        workflow=workflow,
        inputs={"allowed": False},
        metadata={
            "tenant_scope_ref": _sha(f"tenant-{run_id}"),
            "identity_scope_ref": _sha(f"identity-{run_id}"),
            "subject_scope_ref": _sha(f"subject-{run_id}"),
        },
        created_at=_CREATED_AT,
    )


def _worker(task: dict) -> HarnessWorkerResult:
    return HarnessWorkerResult("succeeded", output=task)


def _activate_entry(
    control_plane: HarnessControlPlane,
    run_spec: HarnessRunSpec,
) -> HarnessGraphState:
    initial = control_plane.initialize_graph(run_spec)
    decision = control_plane.next_graph_decision(run_spec, initial)
    assert decision is not None
    return control_plane.apply_graph_decision(
        run_spec,
        initial,
        decision,
        occurred_at=_at(1),
    )


def _enter_plan(
    control_plane: HarnessControlPlane,
    run_spec: HarnessRunSpec,
) -> HarnessGraphState:
    ready = _activate_entry(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        ready,
        graph,
        ready.node_instances[0].instance_id,
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        attempt=0,
        payload={"phase": "plan"},
    )
    return control_plane.apply_graph_decision(
        run_spec,
        ready,
        decision,
        occurred_at=_at(2),
    )


def _dispatch_entry(
    control_plane: HarnessControlPlane,
    run_spec: HarnessRunSpec,
) -> HarnessGraphState:
    planning = _enter_plan(control_plane, run_spec)
    graph = control_plane._prepared_graphs[run_spec.run_id]
    decision = _step_decision(
        planning,
        graph,
        planning.node_instances[0].instance_id,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        attempt=1,
    )
    return control_plane.apply_graph_decision(
        run_spec,
        planning,
        decision,
        occurred_at=_at(4),
        activity_input_ref=_sha("worker-input"),
    )


def _activation_decision(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
    node_id: str,
) -> HarnessGraphDecision:
    definition = _definition(graph, node_id)
    return HarnessGraphDecision(
        HarnessGraphDecisionType.ACTIVATE_NODE,
        state.run_id,
        state.graph_ref,
        state.projection_checksum,
        _sha(f"observations-{state.projection_checksum}"),
        "node_ready",
        node_id=node_id,
        binding_versions=_bindings(definition),
    )


def _control_decision(
    state: HarnessGraphState,
    decision_type: HarnessGraphDecisionType,
    *,
    node_id: str,
    node_instance_id: str,
    target_node_ids: tuple[str, ...] = (),
    payload: dict | None = None,
    binding_versions: dict[str, str] | None = None,
) -> HarnessGraphDecision:
    return HarnessGraphDecision(
        decision_type,
        state.run_id,
        state.graph_ref,
        state.projection_checksum,
        _sha(f"observations-{state.projection_checksum}"),
        f"test_{decision_type.value}",
        node_id=node_id,
        node_instance_id=node_instance_id,
        target_node_ids=target_node_ids,
        binding_versions={} if binding_versions is None else binding_versions,
        payload={} if payload is None else payload,
    )


def _step_decision(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
    node_instance_id: str,
    decision_type: HarnessGraphDecisionType,
    *,
    attempt: int,
    payload: dict | None = None,
) -> HarnessGraphDecision:
    node = next(
        item for item in state.node_instances if item.instance_id == node_instance_id
    )
    definition = _definition(graph, node.identity.node_id)
    return HarnessGraphDecision(
        decision_type,
        state.run_id,
        state.graph_ref,
        state.projection_checksum,
        _sha(f"observations-{state.projection_checksum}"),
        f"test_{decision_type.value}",
        node_id=definition.node_id,
        node_instance_id=node.instance_id,
        step_ref=definition.step_ref,
        attempt=attempt,
        binding_versions=_bindings(definition),
        payload={} if payload is None else payload,
    )


def _definition(
    graph: NormalizedHarnessGraph,
    node_id: str,
) -> HarnessExecutableNode:
    definition = next(item for item in graph.nodes if item.node_id == node_id)
    assert isinstance(definition, HarnessExecutableNode)
    return definition


def _bindings(definition: HarnessExecutableNode) -> dict[str, str]:
    return {
        "step": definition.step_ref.exact_ref,
        "worker": definition.worker_ref.exact_ref,
        "activity": definition.activity_ref.exact_ref,
    }


def _worker_status_observation(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
) -> HarnessAcceptedGraphObservation:
    node = state.node_instances[0]
    definition = _definition(graph, node.identity.node_id)
    return HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.WORKER_STATUS,
        definition.node_id,
        node.instance_id,
        node.attempt,
        state.last_event_sequence + 1,
        definition.worker_ref,
        _sha(f"worker-status-{state.run_id}-{node.attempt}"),
        payload={"status": "succeeded"},
    )


def _sha(value: str) -> str:
    return canonical_checksum({"value": value})


def _at(minutes: int) -> datetime:
    return _CREATED_AT + timedelta(minutes=minutes)


class _RecordingDispatcher:
    def __init__(
        self,
        port: HarnessGraphTransitionPort,
        *,
        assert_committed: bool = False,
    ) -> None:
        self.port = port
        self.assert_committed = assert_committed
        self.calls: list[HarnessGraphActivity] = []
        self.cancellation_calls: list[HarnessGraphActivityCancellationRequest] = []

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        if self.assert_committed:
            recovery = self.port.recover_graph(activity.run_id)
            assert recovery.state is not None
            assert any(
                item.activity_id == activity.activity_id
                for item in recovery.state.active_activities
            )
            assert any(
                item.cause_checksum == activity.causal_decision_checksum
                for item in recovery.projection_commits
            )
        self.calls.append(activity)

    def request_cancellation(
        self,
        request: HarnessGraphActivityCancellationRequest,
    ) -> None:
        recovery = self.port.recover_graph(request.run_id)
        assert recovery.state is not None
        assert any(
            item.instance_id == request.node_instance_id
            and item.status is HarnessNodeInstanceStatus.CANCEL_REQUESTED
            for item in recovery.state.node_instances
        )
        assert any(
            item.cause_checksum == request.causal_decision_checksum
            for item in recovery.projection_commits
        )
        self.cancellation_calls.append(request)


class _FailOnceCancellationDispatcher(_RecordingDispatcher):
    def __init__(self, port: HarnessGraphTransitionPort) -> None:
        super().__init__(port)
        self.cancellation_attempts: list[HarnessGraphActivityCancellationRequest] = []
        self.failed = False

    def request_cancellation(
        self,
        request: HarnessGraphActivityCancellationRequest,
    ) -> None:
        self.cancellation_attempts.append(request)
        if not self.failed:
            self.failed = True
            raise RuntimeError("cancellation unavailable")
        super().request_cancellation(request)


class _FailOnceDispatcher(_RecordingDispatcher):
    def __init__(self, port: HarnessGraphTransitionPort) -> None:
        super().__init__(port, assert_committed=True)
        self.failed = False

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        super().dispatch(activity)
        if not self.failed:
            self.failed = True
            raise RuntimeError("dispatch unavailable")


class _FaultInjectingEventPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_initialization = False
        self.fail_next_decision = False
        self.fail_next_projection = False
        self.fail_next_activity_result = False

    def initialize_graph(self, *args, **kwargs):
        if self.fail_next_initialization:
            self.fail_next_initialization = False
            raise RuntimeError("initialization store unavailable")
        return super().initialize_graph(*args, **kwargs)

    def commit_graph_decision(self, *args, **kwargs):
        if self.fail_next_decision:
            self.fail_next_decision = False
            raise RuntimeError("decision store unavailable")
        return super().commit_graph_decision(*args, **kwargs)

    def commit_graph_projection(self, *args, **kwargs):
        if self.fail_next_projection:
            self.fail_next_projection = False
            raise RuntimeError("projection unavailable")
        return super().commit_graph_projection(*args, **kwargs)

    def commit_graph_activity_result(self, *args, **kwargs):
        if self.fail_next_activity_result:
            self.fail_next_activity_result = False
            raise RuntimeError("activity result store unavailable")
        return super().commit_graph_activity_result(*args, **kwargs)
