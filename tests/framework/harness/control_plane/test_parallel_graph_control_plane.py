from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    CountingHarnessSideEffectHandler,
    HarnessControlPlane,
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphCommitKind,
    HarnessGraphDecisionType,
    HarnessJoinStatus,
    HarnessNodeInstanceStatus,
    HarnessRunSpec,
    HarnessSideEffectCapabilities,
    HarnessSideEffectDecision,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectOutcome,
    HarnessSideEffectRegistry,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    InMemoryHarnessEventPort,
    InMemoryHarnessSideEffectStore,
    RunLifecycle,
    RunOutcome,
    harness_worker_candidate_ref,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.dsl import (
    HarnessGraphSpec,
    ParallelAll,
    ParallelAny,
    ParallelBranch,
    Sequence,
    StepRef,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.validation import HarnessGraphPreflightPolicy
from framework.harness.graph.validation import HarnessGraphPreflight


_CREATED_AT = datetime(2026, 7, 31, 4, 0, tzinfo=UTC)
_IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "parallel-test"})
_SUBJECT_SCOPE_REF = checksum_for({"subject_id": "parallel-paper"})
_PARALLEL_SAFE_CAPABILITIES = HarnessActivityCapabilities(
    termination_confirmation=True,
    stable_idempotency=True,
    fencing=True,
    reconciliation=True,
)
_PARALLEL_SAFE_SIDE_EFFECT_CAPABILITIES = HarnessSideEffectCapabilities(
    cancellation=True,
    termination_confirmation=True,
    stable_idempotency=True,
    fencing=True,
    reconciliation=True,
)


class _FailAfterDecisionProjectionPort(InMemoryHarnessEventPort):
    def __init__(self, decision_type: HarnessGraphDecisionType) -> None:
        super().__init__()
        self.decision_type = decision_type
        self.failed = False

    def commit_graph_projection(self, commit, **kwargs):
        projected = super().commit_graph_projection(commit, **kwargs)
        if (
            not self.failed
            and projected.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION
        ):
            recovery = self.recover_graph(projected.state.run_id)
            decision = next(
                (
                    item.decision
                    for item in recovery.decision_commits
                    if item.decision.decision_checksum == projected.cause_checksum
                ),
                None,
            )
            if decision is not None and decision.decision_type is self.decision_type:
                self.failed = True
                raise RuntimeError("committed parallel projection response was lost")
        return projected


class _FailBeforeWinnerDecisionPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def commit_graph_decision(self, decision, **kwargs):
        if (
            not self.failed
            and decision.decision_type
            is HarnessGraphDecisionType.SELECT_PARALLEL_WINNER
        ):
            self.failed = True
            raise RuntimeError("injected crash before parallel winner commit")
        return super().commit_graph_decision(decision, **kwargs)


def test_parallel_all_commits_fork_branch_evidence_and_join_before_successor() -> None:
    run_spec = _run_spec("run-parallel-all")
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []
    control_plane = _control_plane(port, worker_calls)

    result = control_plane.run(run_spec)

    assert worker_calls == ["left", "right", "aggregate"]
    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert len(result.graph_state.join_states) == 1
    join = result.graph_state.join_states[0]
    assert join.status is HarnessJoinStatus.SATISFIED
    assert set(join.completed_branch_instances) == {"left-branch", "right-branch"}
    assert set(join.terminal_event_refs) == {"left-branch", "right-branch"}
    nodes = {item.identity.node_id: item for item in result.graph_state.node_instances}
    assert nodes["left"].identity.branch_path == ("left-branch",)
    assert nodes["right"].identity.branch_path == ("right-branch",)
    assert set(nodes["left"].output_refs) == {"activity_result", "left_output"}
    assert set(nodes["right"].output_refs) == {"activity_result", "right_output"}
    assert join.completed_branch_instances == {
        "left-branch": nodes["left"].instance_id,
        "right-branch": nodes["right"].instance_id,
    }
    recovery = port.recover_graph(run_spec.run_id)
    fork = _decision(recovery, HarnessGraphDecisionType.OPEN_FORK)
    joined = _decision(recovery, HarnessGraphDecisionType.SATISFY_JOIN)
    aggregate = _decision(
        recovery,
        HarnessGraphDecisionType.ACTIVATE_NODE,
        node_id="aggregate",
    )
    assert fork.sequence < joined.sequence < aggregate.sequence
    assert set(joined.decision.evidence_refs) == set(join.terminal_event_refs.values())
    branch_activations = tuple(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
        and item.decision.node_id in {"left", "right"}
    )
    first_branch_phase = next(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE
        and item.decision.node_id in {"left", "right"}
    )
    assert len(branch_activations) == 2
    assert (
        max(item.sequence for item in branch_activations) < first_branch_phase.sequence
    )


@pytest.mark.parametrize(
    ("max_parallelism", "expected_node_ids"),
    ((1, ["left"]), (2, ["left", "right"])),
)
def test_external_dispatch_respects_physical_parallelism_without_local_execution(
    max_parallelism: int,
    expected_node_ids: list[str],
) -> None:
    run_spec = _run_spec(f"run-external-parallelism-{max_parallelism}")
    port = InMemoryHarnessEventPort()
    dispatcher = _AsyncDispatcher()

    result = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(
            ("left", "right", "aggregate"),
        ),
        graph_preflight=_parallel_preflight(max_parallelism=max_parallelism),
        graph_activity_dispatcher=dispatcher,
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.RUNNING
    assert result.graph_state.outcome is RunOutcome.NONE
    assert [item.node_id for item in dispatcher.calls] == expected_node_ids
    assert len(result.graph_state.active_activities) == max_parallelism
    assert len(result.graph_state.active_activities) <= (
        result.graph_state.budgets.require("max_parallelism").limit
    )


def test_serial_external_dispatcher_does_not_require_concurrency_protocol() -> None:
    run_spec = _run_spec("run-external-serial-dispatcher")
    port = InMemoryHarnessEventPort()
    dispatcher = _SerialOnlyDispatcher()

    result = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(
            ("left", "right", "aggregate"),
        ),
        graph_preflight=_parallel_preflight(max_parallelism=1),
        graph_activity_dispatcher=dispatcher,
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.RUNNING
    assert [item.node_id for item in dispatcher.calls] == ["left"]


def test_external_parallel_results_resume_through_join_and_aggregation() -> None:
    run_spec = _run_spec("run-external-parallel-resume")
    port = InMemoryHarnessEventPort()
    dispatcher = _AsyncDispatcher()
    control_plane = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(
            ("left", "right", "aggregate"),
        ),
        graph_preflight=_parallel_preflight(max_parallelism=2),
        graph_activity_dispatcher=dispatcher,
    )

    running = control_plane.run(run_spec)

    assert running.graph_state is not None
    assert running.graph_state.lifecycle is RunLifecycle.RUNNING
    assert [item.node_id for item in dispatcher.calls] == ["left", "right"]
    for index, activity in enumerate(tuple(dispatcher.calls), start=1):
        _accept_external_result(
            control_plane,
            port,
            run_spec,
            activity,
            offset=100 + index,
        )

    aggregation_running = control_plane.recover_and_run(run_spec)

    assert aggregation_running.graph_state is not None
    assert aggregation_running.graph_state.lifecycle is RunLifecycle.RUNNING
    assert [item.node_id for item in dispatcher.calls] == [
        "left",
        "right",
        "aggregate",
    ]
    _accept_external_result(
        control_plane,
        port,
        run_spec,
        dispatcher.calls[-1],
        offset=200,
    )

    completed = control_plane.recover_and_run(run_spec)

    assert completed.graph_state is not None
    assert completed.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert completed.graph_state.outcome is RunOutcome.SUCCEEDED
    assert [item.node_id for item in dispatcher.calls] == [
        "left",
        "right",
        "aggregate",
    ]


def test_parallel_all_recovers_after_fork_projection_without_reopening_scope() -> None:
    run_spec = _run_spec("run-parallel-fork-recovery")
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []
    first = _control_plane(port, worker_calls)
    state = first.initialize_graph(run_spec)

    activate = first.next_graph_decision(run_spec, state)
    assert activate is not None
    state = first.apply_graph_decision(
        run_spec,
        state,
        activate,
        occurred_at=_at(2),
    )
    open_fork = first.next_graph_decision(run_spec, state)
    assert open_fork is not None
    assert open_fork.decision_type is HarnessGraphDecisionType.OPEN_FORK
    state = first.apply_graph_decision(
        run_spec,
        state,
        open_fork,
        occurred_at=_at(4),
    )
    assert len(state.join_states) == 1
    join_instance_id = state.join_states[0].join_instance_id

    recovered = _control_plane(port, worker_calls).recover_and_run(run_spec)

    assert recovered.graph_state is not None
    assert recovered.graph_state.outcome is RunOutcome.SUCCEEDED
    assert [item.join_instance_id for item in recovered.graph_state.join_states] == [
        join_instance_id
    ]
    recovery = port.recover_graph(run_spec.run_id)
    assert (
        sum(
            item.decision.decision_type is HarnessGraphDecisionType.OPEN_FORK
            for item in recovery.decision_commits
        )
        == 1
    )
    assert worker_calls == ["left", "right", "aggregate"]


def test_parallel_any_commits_winner_then_cancels_undispatched_loser() -> None:
    run_spec = _parallel_any_run_spec("run-parallel-any")
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    result = _control_plane(port, worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["left", "aggregate"]
    join = result.graph_state.join_states[0]
    assert join.status is HarnessJoinStatus.SATISFIED
    assert join.winner_branch_id == "left-branch"
    assert set(join.completed_branch_instances) == {"left-branch", "right-branch"}
    nodes = {item.identity.node_id: item for item in result.graph_state.node_instances}
    assert nodes["right"].status is HarnessNodeInstanceStatus.CANCELLED

    recovery = port.recover_graph(run_spec.run_id)
    winner = _decision(recovery, HarnessGraphDecisionType.SELECT_PARALLEL_WINNER)
    loser_cancel = _decision(
        recovery,
        HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
        node_id="right",
    )
    aggregate = _decision(
        recovery,
        HarnessGraphDecisionType.ACTIVATE_NODE,
        node_id="aggregate",
    )
    assert winner.sequence < aggregate.sequence
    assert winner.sequence < loser_cancel.sequence < aggregate.sequence
    assert winner.decision.evidence_refs == (join.terminal_event_refs["left-branch"],)


def test_parallel_any_wait_for_losers_preserves_late_verified_result() -> None:
    run_spec = _parallel_any_run_spec(
        "run-parallel-any-wait-losers",
        cancellation_policy="wait_for_losers",
    )
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    result = _control_plane(port, worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["left", "right", "aggregate"]
    join = result.graph_state.join_states[0]
    assert join.winner_branch_id == "left-branch"
    assert set(join.completed_branch_instances) == {"left-branch", "right-branch"}
    recovery = port.recover_graph(run_spec.run_id)
    assert all(
        item.decision.decision_type
        is not HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL
        for item in recovery.decision_commits
    )


def test_parallel_any_all_failed_records_aggregate_failure_without_winner() -> None:
    run_spec = _parallel_any_run_spec("run-parallel-any-all-failed")
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("failed", error=f"{task['step_id']} failed")

    result = HarnessControlPlane(
        event_port=port,
        worker_registry={step_id: worker for step_id in ("left", "right", "aggregate")},
        graph_preflight=_parallel_preflight(),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.FAILED
    assert worker_calls == ["left", "right"]
    join = result.graph_state.join_states[0]
    assert join.status is HarnessJoinStatus.FAILED
    assert join.winner_branch_id is None
    recovery = port.recover_graph(run_spec.run_id)
    failed_join = _decision(recovery, HarnessGraphDecisionType.FAIL_JOIN)
    assert failed_join.decision.reason_code == "parallel_any_all_branches_failed"
    assert all(
        item.decision.decision_type
        is not HarnessGraphDecisionType.SELECT_PARALLEL_WINNER
        for item in recovery.decision_commits
    )


def test_parallel_any_preserves_committed_loser_side_effect_outcome() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="parallel-any-effects",
        steps=tuple(
            HarnessStepSpec(
                step_id,
                "artifact",
                output_key=f"{step_id}_output",
                side_effect_handler="parallel.publish@1",
            )
            for step_id in ("left", "right")
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            "parallel-any-effects",
            ParallelAny(
                "fork",
                "join",
                (
                    ParallelBranch("left-branch", StepRef("left"), "parallel.left"),
                    ParallelBranch("right-branch", StepRef("right"), "parallel.right"),
                ),
                cancellation_policy="wait_for_losers",
            ),
        ),
    )
    run_spec = HarnessRunSpec(
        "run-parallel-any-effects",
        workflow,
        metadata={
            "identity_scope_ref": _IDENTITY_SCOPE_REF,
            "subject_scope_ref": _SUBJECT_SCOPE_REF,
        },
        created_at=_CREATED_AT,
    )
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)

    def worker(task: dict) -> HarnessWorkerResult:
        output = {"candidate": task["step_id"]}
        candidate = {
            "status": "succeeded",
            "output": output,
            "artifacts": [],
            "diagnostics": {},
            "metrics": {},
            "error": None,
        }
        return HarnessWorkerResult(
            "succeeded",
            output=output,
            effect_intent=HarnessSideEffectIntent(
                effect_id=f"effect-{task['step_id']}",
                kind="artifact",
                run_id=task["run_id"],
                origin="worker",
                atomic_group="parallel-effects",
                identity_scope_ref=_IDENTITY_SCOPE_REF,
                subject_scope_ref=_SUBJECT_SCOPE_REF,
                attempt=task["harness_activity"]["attempt"],
                step_id=task["step_id"],
                worker_result_ref=harness_worker_candidate_ref(candidate),
                candidate_checksum=checksum_for(output),
                handler="parallel.publish@1",
            ),
        )

    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"left": worker, "right": worker},
        side_effect_registry=HarnessSideEffectRegistry(
            (
                HarnessSideEffectHandlerBinding(
                    "parallel.publish@1",
                    "artifact",
                    handler,
                ),
            )
        ),
        side_effect_store=store,
        graph_preflight=_parallel_preflight(),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.join_states[0].winner_branch_id == "left-branch"
    assert set(result.side_effect_outcomes) == {"left", "right"}
    assert handler.call_count == 2
    assert store.outcome_write_count == 2


def test_parallel_side_effect_preflight_requires_fenced_binding_and_store() -> None:
    run_spec = _parallel_effect_run_spec("run-parallel-unsafe-effects")
    port = InMemoryHarnessEventPort()
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    worker_calls: list[str] = []

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=port,
            worker_registry={
                step_id: _parallel_effect_worker(worker_calls)
                for step_id in ("left", "right")
            },
            side_effect_registry=HarnessSideEffectRegistry(
                (
                    HarnessSideEffectHandlerBinding(
                        "parallel.fenced@1",
                        "artifact",
                        handler,
                    ),
                )
            ),
            side_effect_store=store,
            graph_preflight=_parallel_preflight(max_parallelism=2),
        ).run(run_spec)

    assert captured.value.code == "harness_graph_preflight_failed"
    assert any(
        item["code"] == "parallel_side_effect_safety_unproven"
        for item in captured.value.details["diagnostics"]
    )
    assert port.read_history(run_spec.run_id) == ()
    assert worker_calls == []


def test_parallel_side_effects_commit_through_fenced_handler_and_store() -> None:
    run_spec = _parallel_effect_run_spec("run-parallel-fenced-effects")
    store = InMemoryHarnessSideEffectStore()
    handler = _FencedEffectHandler(store, persist_before_return=True)
    port = InMemoryHarnessEventPort()
    dispatcher = _AsyncDispatcher()
    side_effect_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "parallel.fenced@1",
                "artifact",
                handler,
                capabilities=_PARALLEL_SAFE_SIDE_EFFECT_CAPABILITIES,
            ),
        )
    )

    control_plane = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(
            ("left", "right"),
            side_effect_registry=side_effect_registry,
        ),
        side_effect_store=store,
        graph_preflight=_parallel_preflight(max_parallelism=2),
        graph_activity_dispatcher=dispatcher,
    )
    running = control_plane.run(run_spec)
    assert running.graph_state is not None
    assert [item.node_id for item in dispatcher.calls] == ["left", "right"]
    for index, activity in enumerate(tuple(dispatcher.calls), start=1):
        _accept_external_effect_result(
            control_plane,
            port,
            run_spec,
            activity,
            offset=100 + index,
        )

    result = control_plane.recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert handler.serial_calls == 0
    assert handler.fenced_calls == 2
    assert store.outcome_write_count == 2
    assert set(result.side_effect_outcomes) == {"left", "right"}
    for outcome in result.side_effect_outcomes.values():
        assert outcome.attempt_id is not None
        assert outcome.fencing_generation == 1


def test_concurrent_reconciliation_commits_one_fenced_outcome() -> None:
    clock = _MutableClock()
    store = InMemoryHarnessSideEffectStore(
        attempt_lease_seconds=30,
        clock=clock,
    )
    intent = _direct_effect_intent("run-concurrent-reconcile")
    authorization = _direct_effect_decision(intent, effect_attempt_limit=2)
    store.put_decision(authorization)
    original = store.acquire_attempt(
        authorization,
        owner_id="crashed-owner",
        lease_id="crashed-lease",
    )
    clock.advance(31)
    barrier = Barrier(2)
    handler = _FencedEffectHandler(
        store,
        reconcile_barrier=barrier,
        persist_before_return=False,
    )
    binding = HarnessSideEffectHandlerBinding(
        "parallel.fenced@1",
        "artifact",
        handler,
        capabilities=_PARALLEL_SAFE_SIDE_EFFECT_CAPABILITIES,
    )
    control_planes = tuple(
        HarnessControlPlane(
            event_port=InMemoryHarnessEventPort(),
            side_effect_registry=HarnessSideEffectRegistry((binding,)),
            side_effect_store=store,
        )
        for _ in range(2)
    )

    def reconcile(control_plane: HarnessControlPlane) -> HarnessSideEffectOutcome:
        return control_plane._execute_fenced_side_effect(
            intent,
            authorization,
            binding=binding,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(reconcile, control_planes))

    assert outcomes[0] == outcomes[1]
    assert outcomes[0].attempt_id == original.attempt_id
    assert store.outcome_write_count == 1
    assert store.attempts_by_effect[intent.effect_id] == 1
    assert handler.reconcile_calls == 2
    assert handler.fenced_calls == 0


def test_failed_fenced_effect_requests_cancellation_before_confirmation() -> None:
    store = InMemoryHarnessSideEffectStore()
    intent = _direct_effect_intent("run-fenced-cancellation-order")
    authorization = _direct_effect_decision(intent, effect_attempt_limit=2)
    store.put_decision(authorization)
    handler = _ProtocolTrackingFencedHandler(fail_commit=True)
    binding = HarnessSideEffectHandlerBinding(
        "parallel.fenced@1",
        "artifact",
        handler,
        capabilities=_PARALLEL_SAFE_SIDE_EFFECT_CAPABILITIES,
    )
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        side_effect_registry=HarnessSideEffectRegistry((binding,)),
        side_effect_store=store,
    )

    with pytest.raises(RuntimeError, match="fenced commit failed"):
        control_plane._execute_fenced_side_effect(
            intent,
            authorization,
            binding=binding,
        )

    assert handler.calls == ["commit", "cancel", "reconcile", "confirm"]
    attempt = store.get_attempt(
        effect_id=intent.effect_id,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
    )
    assert attempt is not None
    assert attempt.termination_confirmed is True


def test_success_after_lease_expiry_reconciles_same_fenced_attempt() -> None:
    clock = _MutableClock()
    store = InMemoryHarnessSideEffectStore(
        attempt_lease_seconds=30,
        clock=clock,
    )
    intent = _direct_effect_intent("run-fenced-expired-completion")
    authorization = _direct_effect_decision(intent, effect_attempt_limit=2)
    store.put_decision(authorization)
    handler = _ProtocolTrackingFencedHandler(
        clock=clock,
        reconcile_outcome=True,
    )
    binding = HarnessSideEffectHandlerBinding(
        "parallel.fenced@1",
        "artifact",
        handler,
        capabilities=_PARALLEL_SAFE_SIDE_EFFECT_CAPABILITIES,
    )
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        side_effect_registry=HarnessSideEffectRegistry((binding,)),
        side_effect_store=store,
    )

    outcome = control_plane._execute_fenced_side_effect(
        intent,
        authorization,
        binding=binding,
    )

    assert handler.calls == ["commit", "cancel", "reconcile"]
    assert outcome.schema_version == "newsroom.harness-side-effect-outcome/v2"
    assert outcome.fencing_generation == 1
    attempt = store.get_attempt(
        effect_id=intent.effect_id,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
    )
    assert attempt is not None
    assert attempt.attempt == 1
    assert attempt.termination_confirmed is True
    assert attempt.outcome_ref == outcome.checksum
    assert store.outcome_write_count == 1


def test_parallel_any_recovers_committed_winner_without_reselection() -> None:
    run_spec = _parallel_any_run_spec("run-parallel-any-winner-recovery")
    port = _FailAfterDecisionProjectionPort(
        HarnessGraphDecisionType.SELECT_PARALLEL_WINNER
    )
    worker_calls: list[str] = []

    with pytest.raises(RuntimeError, match="projection response was lost"):
        _control_plane(port, worker_calls).run(run_spec)

    result = _control_plane(port, worker_calls).recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert result.graph_state.join_states[0].winner_branch_id == "left-branch"
    recovery = port.recover_graph(run_spec.run_id)
    assert (
        sum(
            item.decision.decision_type
            is HarnessGraphDecisionType.SELECT_PARALLEL_WINNER
            for item in recovery.decision_commits
        )
        == 1
    )
    assert worker_calls == ["left", "aggregate"]


def test_parallel_any_recovers_before_winner_commit_without_worker_reexecution() -> (
    None
):
    run_spec = _parallel_any_run_spec("run-parallel-any-pre-winner-recovery")
    port = _FailBeforeWinnerDecisionPort()
    worker_calls: list[str] = []

    with pytest.raises(RuntimeError, match="before parallel winner commit"):
        _control_plane(port, worker_calls).run(run_spec)

    interrupted = port.recover_graph(run_spec.run_id)
    assert all(
        item.decision.decision_type
        is not HarnessGraphDecisionType.SELECT_PARALLEL_WINNER
        for item in interrupted.decision_commits
    )
    calls_before_restart = tuple(worker_calls)

    result = _control_plane(port, worker_calls).recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert result.graph_state.join_states[0].winner_branch_id == "left-branch"
    assert tuple(worker_calls[: len(calls_before_restart)]) == calls_before_restart
    assert worker_calls == ["left", "aggregate"]
    recovery = port.recover_graph(run_spec.run_id)
    assert (
        sum(
            item.decision.decision_type
            is HarnessGraphDecisionType.SELECT_PARALLEL_WINNER
            for item in recovery.decision_commits
        )
        == 1
    )


def test_parallel_all_recovers_committed_join_without_reexecution() -> None:
    run_spec = _run_spec("run-parallel-all-join-recovery")
    port = _FailAfterDecisionProjectionPort(HarnessGraphDecisionType.SATISFY_JOIN)
    worker_calls: list[str] = []

    with pytest.raises(RuntimeError, match="projection response was lost"):
        _control_plane(port, worker_calls).run(run_spec)

    result = _control_plane(port, worker_calls).recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert result.graph_state.join_states[0].status is HarnessJoinStatus.SATISFIED
    recovery = port.recover_graph(run_spec.run_id)
    assert (
        sum(
            item.decision.decision_type is HarnessGraphDecisionType.SATISFY_JOIN
            for item in recovery.decision_commits
        )
        == 1
    )
    assert worker_calls == ["left", "right", "aggregate"]


def test_parallel_all_fail_fast_cancels_undispatched_sibling_before_join_failure() -> (
    None
):
    run_spec = _parallel_all_failure_run_spec(
        "run-parallel-fail-fast",
        failure_policy="fail_fast",
    )
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        if task["step_id"] == "bad":
            return HarnessWorkerResult("failed", error="expected")
        return HarnessWorkerResult("succeeded", output={"unexpected": True})

    result = _failure_control_plane(port, worker).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.FAILED
    assert worker_calls == ["bad"]
    states = {
        item.identity.node_id: item.status for item in result.graph_state.node_instances
    }
    assert states["bad"] is HarnessNodeInstanceStatus.FAILED
    assert states["good"] is HarnessNodeInstanceStatus.CANCELLED
    recovery = port.recover_graph(run_spec.run_id)
    cancel = _decision(
        recovery,
        HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
        node_id="good",
    )
    failed_join = _decision(recovery, HarnessGraphDecisionType.FAIL_JOIN)
    assert cancel.sequence < failed_join.sequence
    assert all(
        item.decision.node_id != "good"
        or item.decision.decision_type is not HarnessGraphDecisionType.DISPATCH_ACTIVITY
        for item in recovery.decision_commits
    )


def test_parallel_all_wait_all_runs_remaining_branch_before_join_failure() -> None:
    run_spec = _parallel_all_failure_run_spec(
        "run-parallel-wait-all",
        failure_policy="wait_all",
    )
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        if task["step_id"] == "bad":
            return HarnessWorkerResult("failed", error="expected")
        return HarnessWorkerResult("succeeded", output={"ok": True})

    result = _failure_control_plane(port, worker).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.FAILED
    assert worker_calls == ["bad", "good"]
    recovery = port.recover_graph(run_spec.run_id)
    good_completion = _decision(
        recovery,
        HarnessGraphDecisionType.COMPLETE_NODE,
        node_id="good",
    )
    failed_join = _decision(recovery, HarnessGraphDecisionType.FAIL_JOIN)
    assert good_completion.sequence < failed_join.sequence
    assert all(
        item.decision.decision_type
        is not HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL
        for item in recovery.decision_commits
    )


@pytest.mark.parametrize(
    ("termination_confirmed", "expected_lifecycle", "expected_outcome"),
    (
        (True, RunLifecycle.COMPLETED, RunOutcome.FAILED),
        (False, RunLifecycle.HALTED, RunOutcome.INDETERMINATE),
    ),
)
def test_parallel_all_fail_fast_waits_for_confirmed_active_sibling_termination(
    termination_confirmed: bool,
    expected_lifecycle: RunLifecycle,
    expected_outcome: RunOutcome,
) -> None:
    run_spec = _parallel_all_failure_run_spec(
        f"run-parallel-fail-fast-active-{termination_confirmed}",
        failure_policy="fail_fast",
    )
    port = InMemoryHarnessEventPort()
    dispatcher = _AsyncDispatcher()
    control_plane = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(("bad", "good")),
        graph_preflight=_parallel_preflight(max_parallelism=2),
        graph_activity_dispatcher=dispatcher,
    )

    running = control_plane.run(run_spec)
    assert running.graph_state is not None
    assert [item.node_id for item in dispatcher.calls] == ["bad", "good"]
    bad_activity, good_activity = dispatcher.calls

    _accept_external_activity_result(
        control_plane,
        port,
        run_spec,
        bad_activity,
        status="failed",
        termination_confirmed=True,
        offset=100,
    )
    pending_cancel = control_plane.recover_and_run(run_spec)
    assert pending_cancel.graph_state is not None
    assert pending_cancel.graph_state.lifecycle is RunLifecycle.RUNNING
    assert pending_cancel.graph_state.join_states[0].status is HarnessJoinStatus.OPEN
    good_node = next(
        item
        for item in pending_cancel.graph_state.node_instances
        if item.identity.node_id == "good"
    )
    assert good_node.status is HarnessNodeInstanceStatus.CANCEL_REQUESTED
    assert len(dispatcher.cancellation_requests) == 1

    _accept_external_activity_result(
        control_plane,
        port,
        run_spec,
        good_activity,
        status="cancelled",
        termination_confirmed=termination_confirmed,
        offset=200,
    )
    if termination_confirmed:
        completed = control_plane.recover_and_run(run_spec)
        assert completed.graph_state is not None
        assert completed.graph_state.lifecycle is expected_lifecycle
        assert completed.graph_state.outcome is expected_outcome
        recovery = port.recover_graph(run_spec.run_id)
        cancel = _decision(
            recovery,
            HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
            node_id="good",
        )
        failed_join = _decision(recovery, HarnessGraphDecisionType.FAIL_JOIN)
        assert cancel.sequence < failed_join.sequence
    else:
        halted = control_plane.recover_graph(run_spec)
        assert halted.lifecycle is expected_lifecycle
        assert halted.outcome is expected_outcome
        assert halted.active_activities
        assert halted.join_states[0].status is HarnessJoinStatus.OPEN
        assert not any(
            item.decision.decision_type is HarnessGraphDecisionType.FAIL_JOIN
            for item in port.recover_graph(run_spec.run_id).decision_commits
        )


@pytest.mark.parametrize(
    ("failure_policy", "expected_calls"),
    (
        ("fail_fast", ["bad"]),
        ("wait_all", ["bad", "good"]),
        ("compensate", ["bad", "good"]),
    ),
)
def test_parallel_all_composite_branch_failure_reaches_owning_join(
    failure_policy: str,
    expected_calls: list[str],
) -> None:
    run_spec = _parallel_all_composite_failure_run_spec(
        f"run-parallel-composite-{failure_policy}",
        failure_policy=failure_policy,
    )
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        if task["step_id"] == "bad":
            return HarnessWorkerResult("failed", error="expected")
        return HarnessWorkerResult("succeeded", output={"ok": True})

    result = HarnessControlPlane(
        event_port=port,
        worker_registry={step_id: worker for step_id in ("bad", "never", "good")},
        graph_preflight=_parallel_preflight(),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.FAILED
    assert worker_calls == expected_calls
    assert "never" not in worker_calls
    join = result.graph_state.join_states[0]
    assert join.status is HarnessJoinStatus.FAILED
    assert set(join.completed_branch_instances) == {"bad-branch", "good-branch"}
    bad_instance_id = join.completed_branch_instances["bad-branch"]
    bad_instance = next(
        item
        for item in result.graph_state.node_instances
        if item.instance_id == bad_instance_id
    )
    assert bad_instance.identity.node_id == "bad"
    if failure_policy == "compensate":
        assert result.graph_state.metadata["execution_mode"] == "compensating"


@pytest.mark.parametrize(
    "missing_capability",
    (
        "termination_confirmation",
        "stable_idempotency",
        "fencing",
        "reconciliation",
    ),
)
def test_parallel_preflight_rejects_unsafe_dispatcher_despite_safe_binding(
    missing_capability: str,
) -> None:
    run_spec = _run_spec(f"run-parallel-unsafe-{missing_capability}")
    port = InMemoryHarnessEventPort()
    capabilities = {
        "termination_confirmation": True,
        "stable_idempotency": True,
        "fencing": True,
        "reconciliation": True,
    }
    capabilities[missing_capability] = False
    dispatcher = _AsyncDispatcher(HarnessActivityCapabilities(**capabilities))

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=port,
            runtime_binding_authority=_external_authority(
                ("left", "right", "aggregate"),
            ),
            graph_preflight=_parallel_preflight(max_parallelism=2),
            graph_activity_dispatcher=dispatcher,
        ).run(run_spec)

    assert captured.value.code == "harness_graph_preflight_failed"
    diagnostics = captured.value.details["diagnostics"]
    assert any(
        item["code"] == "parallel_activity_safety_unproven" for item in diagnostics
    )
    assert port.read_history(run_spec.run_id) == ()
    assert dispatcher.calls == []


def test_parallel_preflight_rejects_dispatcher_without_cancellation_capability() -> (
    None
):
    run_spec = _run_spec("run-parallel-missing-cancellation")
    port = InMemoryHarnessEventPort()
    dispatcher = _DispatcherWithoutCancellation()

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=port,
            runtime_binding_authority=_external_authority(
                ("left", "right", "aggregate"),
            ),
            graph_preflight=_parallel_preflight(max_parallelism=2),
            graph_activity_dispatcher=dispatcher,
        ).run(run_spec)

    assert captured.value.code == "harness_graph_preflight_failed"
    assert any(
        item["code"] == "parallel_activity_safety_unproven"
        for item in captured.value.details["diagnostics"]
    )
    assert port.read_history(run_spec.run_id) == ()
    assert dispatcher.calls == []


def test_parallel_dispatch_revalidates_pinned_dispatcher_capabilities() -> None:
    run_spec = _run_spec("run-parallel-capability-drift")
    port = InMemoryHarnessEventPort()
    dispatcher = _CapabilityChangingDispatcher()

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=port,
            runtime_binding_authority=_external_authority(
                ("left", "right", "aggregate"),
            ),
            graph_preflight=_parallel_preflight(max_parallelism=2),
            graph_activity_dispatcher=dispatcher,
        ).run(run_spec)

    assert captured.value.code == "graph_activity_dispatcher_capabilities_changed"
    assert dispatcher.capability_queries == 2
    assert dispatcher.calls == []
    assert port.recover_graph(run_spec.run_id).activities


@pytest.mark.parametrize("status", ("failed", "timeout", "cancelled"))
def test_non_success_activity_result_requires_explicit_termination_confirmation(
    status: str,
) -> None:
    run_spec = _run_spec(f"run-result-confirmation-required-{status}")
    port = InMemoryHarnessEventPort()
    dispatcher = _AsyncDispatcher()
    control_plane = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(
            ("left", "right", "aggregate"),
        ),
        graph_preflight=_parallel_preflight(max_parallelism=1),
        graph_activity_dispatcher=dispatcher,
    )
    control_plane.run(run_spec)
    activity = dispatcher.calls[0]

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphActivityResult.for_activity(
            activity,
            evidence_ref=checksum_for({"status": status, "kind": "evidence"}),
            payload_ref=checksum_for({"status": status, "kind": "payload"}),
            status=status,
        )

    assert captured.value.code == "graph_activity_termination_confirmation_missing"
    assert port.recover_graph(run_spec.run_id).activity_result_commits == ()


@pytest.mark.parametrize("status", ("failed", "timeout", "cancelled"))
def test_unconfirmed_non_success_keeps_parallel_slot_and_blocks_replacement(
    status: str,
) -> None:
    run_spec = _run_spec(f"run-unconfirmed-slot-{status}")
    port = InMemoryHarnessEventPort()
    dispatcher = _AsyncDispatcher()
    control_plane = HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=_external_authority(
            ("left", "right", "aggregate"),
        ),
        graph_preflight=_parallel_preflight(max_parallelism=1),
        graph_activity_dispatcher=dispatcher,
    )
    control_plane.run(run_spec)
    activity = dispatcher.calls[0]

    _accept_external_activity_result(
        control_plane,
        port,
        run_spec,
        activity,
        status=status,
        termination_confirmed=False,
        offset=100,
    )
    halted = control_plane.recover_graph(run_spec)

    assert halted.lifecycle is RunLifecycle.HALTED
    assert halted.outcome is RunOutcome.INDETERMINATE
    assert [item.activity_id for item in halted.active_activities] == [
        activity.activity_id
    ]
    assert [item.node_id for item in dispatcher.calls] == ["left"]
    resumed = control_plane.recover_and_run(run_spec)
    assert resumed.graph_state == halted
    assert [item.node_id for item in dispatcher.calls] == ["left"]


def _run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=tuple(
            HarnessStepSpec(step_id, "script", output_key=f"{step_id}_output")
            for step_id in ("left", "right", "aggregate")
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Sequence(
                (
                    ParallelAll(
                        "fork",
                        "join",
                        (
                            ParallelBranch(
                                "left-branch",
                                StepRef("left"),
                                "parallel.left",
                            ),
                            ParallelBranch(
                                "right-branch",
                                StepRef("right"),
                                "parallel.right",
                            ),
                        ),
                    ),
                    StepRef("aggregate"),
                )
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _parallel_any_run_spec(
    run_id: str,
    *,
    cancellation_policy: str = "cancel_losers",
) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        workflow_version="2",
        steps=tuple(
            HarnessStepSpec(step_id, "script", output_key=f"{step_id}_output")
            for step_id in ("left", "right", "aggregate")
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=Sequence(
                (
                    ParallelAny(
                        "fork",
                        "join",
                        (
                            ParallelBranch(
                                "left-branch",
                                StepRef("left"),
                                "parallel.left",
                            ),
                            ParallelBranch(
                                "right-branch",
                                StepRef("right"),
                                "parallel.right",
                            ),
                        ),
                        cancellation_policy=cancellation_policy,
                    ),
                    StepRef("aggregate"),
                )
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _parallel_all_failure_run_spec(
    run_id: str,
    *,
    failure_policy: str,
) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec("bad", "script"),
            HarnessStepSpec("good", "script"),
        ),
        entry_step_id="bad",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("bad-branch", StepRef("bad"), "parallel.bad"),
                    ParallelBranch("good-branch", StepRef("good"), "parallel.good"),
                ),
                failure_policy=failure_policy,
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _parallel_all_composite_failure_run_spec(
    run_id: str,
    *,
    failure_policy: str,
) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=tuple(
            HarnessStepSpec(step_id, "script") for step_id in ("bad", "never", "good")
        ),
        entry_step_id="bad",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch(
                        "bad-branch",
                        Sequence((StepRef("bad"), StepRef("never"))),
                        "parallel.bad",
                    ),
                    ParallelBranch(
                        "good-branch",
                        StepRef("good"),
                        "parallel.good",
                    ),
                ),
                failure_policy=failure_policy,
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _control_plane(
    port: InMemoryHarnessEventPort,
    worker_calls: list[str],
) -> HarnessControlPlane:
    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult(
            "succeeded",
            output={"step_id": task["step_id"]},
        )

    return HarnessControlPlane(
        event_port=port,
        worker_registry={step_id: worker for step_id in ("left", "right", "aggregate")},
        graph_preflight=_parallel_preflight(),
    )


def _failure_control_plane(port, worker) -> HarnessControlPlane:
    return HarnessControlPlane(
        event_port=port,
        worker_registry={"bad": worker, "good": worker},
        graph_preflight=_parallel_preflight(),
    )


def _parallel_preflight(*, max_parallelism: int = 1) -> HarnessGraphPreflight:
    return HarnessGraphPreflight(
        policy=HarnessGraphPreflightPolicy(
            max_node_activations=20,
            max_active_nodes=4,
            max_parallelism=max_parallelism,
        )
    )


def _decision(recovery, decision_type, *, node_id: str | None = None):
    return next(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is decision_type
        and (node_id is None or item.decision.node_id == node_id)
    )


def _at(offset: int) -> datetime:
    return _CREATED_AT + timedelta(microseconds=offset)


def _accept_external_result(
    control_plane: HarnessControlPlane,
    port: InMemoryHarnessEventPort,
    run_spec: HarnessRunSpec,
    activity: HarnessGraphActivity,
    *,
    offset: int,
) -> None:
    result = HarnessWorkerResult(
        "succeeded",
        output={"step_id": activity.node_id},
    )
    port.activity_results[activity.activity_id] = result
    control_plane.accept_graph_activity_result(
        run_spec,
        HarnessGraphActivityResult.for_activity(
            activity,
            evidence_ref=checksum_for(
                {
                    "activity_id": activity.activity_id,
                    "kind": "external-result",
                }
            ),
            payload_ref=checksum_for(result.to_dict()),
            status="succeeded",
            termination_confirmed=True,
        ),
        occurred_at=_at(offset),
    )


def _accept_external_effect_result(
    control_plane: HarnessControlPlane,
    port: InMemoryHarnessEventPort,
    run_spec: HarnessRunSpec,
    activity: HarnessGraphActivity,
    *,
    offset: int,
) -> None:
    output = {"candidate": activity.node_id}
    candidate = {
        "status": "succeeded",
        "output": output,
        "artifacts": [],
        "diagnostics": {},
        "metrics": {},
        "error": None,
    }
    result = HarnessWorkerResult(
        "succeeded",
        output=output,
        effect_intent=HarnessSideEffectIntent(
            effect_id=f"effect-{activity.run_id}-{activity.node_id}",
            kind="artifact",
            run_id=activity.run_id,
            origin="worker",
            atomic_group="parallel-fenced-effects",
            identity_scope_ref=_IDENTITY_SCOPE_REF,
            subject_scope_ref=_SUBJECT_SCOPE_REF,
            attempt=activity.attempt,
            step_id=activity.node_id,
            worker_result_ref=harness_worker_candidate_ref(candidate),
            candidate_checksum=checksum_for(output),
            handler="parallel.fenced@1",
        ),
    )
    port.activity_results[activity.activity_id] = result
    control_plane.accept_graph_activity_result(
        run_spec,
        HarnessGraphActivityResult.for_activity(
            activity,
            evidence_ref=checksum_for(
                {
                    "activity_id": activity.activity_id,
                    "kind": "external-effect-result",
                }
            ),
            payload_ref=checksum_for(result.to_dict()),
            status="succeeded",
            termination_confirmed=True,
        ),
        occurred_at=_at(offset),
    )


def _accept_external_activity_result(
    control_plane: HarnessControlPlane,
    port: InMemoryHarnessEventPort,
    run_spec: HarnessRunSpec,
    activity: HarnessGraphActivity,
    *,
    status: str,
    termination_confirmed: bool,
    offset: int,
) -> None:
    worker_status = "succeeded" if status == "succeeded" else "failed"
    worker_result = HarnessWorkerResult(
        worker_status,
        output={"step_id": activity.node_id},
        error=None if worker_status == "succeeded" else status,
    )
    port.activity_results[activity.activity_id] = worker_result
    control_plane.accept_graph_activity_result(
        run_spec,
        HarnessGraphActivityResult.for_activity(
            activity,
            evidence_ref=checksum_for(
                {
                    "activity_id": activity.activity_id,
                    "kind": "external-result",
                    "status": status,
                    "termination_confirmed": termination_confirmed,
                }
            ),
            payload_ref=checksum_for(worker_result.to_dict()),
            status=status,
            termination_confirmed=termination_confirmed,
        ),
        occurred_at=_at(offset),
    )


class _AsyncDispatcher:
    def __init__(
        self,
        capabilities: HarnessActivityCapabilities | None = _PARALLEL_SAFE_CAPABILITIES,
    ) -> None:
        self.calls: list[HarnessGraphActivity] = []
        self.cancellation_requests: list[object] = []
        self.capabilities = capabilities

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        self.calls.append(activity)

    def request_cancellation(self, request: object) -> None:
        self.cancellation_requests.append(request)

    def concurrency_capabilities_for(
        self,
        _activity_ref: object,
    ) -> HarnessActivityCapabilities | None:
        return self.capabilities


class _DispatcherWithoutCancellation:
    def __init__(self) -> None:
        self.calls: list[HarnessGraphActivity] = []

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        self.calls.append(activity)

    def concurrency_capabilities_for(
        self,
        _activity_ref: object,
    ) -> HarnessActivityCapabilities:
        return _PARALLEL_SAFE_CAPABILITIES


class _SerialOnlyDispatcher:
    def __init__(self) -> None:
        self.calls: list[HarnessGraphActivity] = []

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        self.calls.append(activity)


class _CapabilityChangingDispatcher(_AsyncDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self.capability_queries = 0

    def concurrency_capabilities_for(
        self,
        _activity_ref: object,
    ) -> HarnessActivityCapabilities:
        self.capability_queries += 1
        if self.capability_queries == 1:
            return _PARALLEL_SAFE_CAPABILITIES
        return HarnessActivityCapabilities(
            termination_confirmation=True,
            stable_idempotency=True,
            fencing=True,
            reconciliation=False,
        )


class _ExternalWorker:
    worker_version = "1"
    worker_type = "script"

    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id

    def execute(self, _task: dict) -> HarnessWorkerResult:
        raise AssertionError("external dispatch must not execute a local Worker")


class _ParallelSafeActivity:
    activity_contract_id = "newsroom.harness-worker-activity"
    activity_contract_version = "v1"
    capabilities = _PARALLEL_SAFE_CAPABILITIES

    def dispatch(self, _request: dict) -> None:
        raise AssertionError("Graph dispatcher owns external activity dispatch")


class _MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _FencedEffectHandler:
    def __init__(
        self,
        store: InMemoryHarnessSideEffectStore,
        *,
        persist_before_return: bool,
        reconcile_barrier: Barrier | None = None,
    ) -> None:
        self.store = store
        self.persist_before_return = persist_before_return
        self.reconcile_barrier = reconcile_barrier
        self.serial_calls = 0
        self.fenced_calls = 0
        self.reconcile_calls = 0

    def commit(
        self,
        _intent: HarnessSideEffectIntent,
        _authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        self.serial_calls += 1
        raise AssertionError("fenced side-effect must not use serial commit")

    def commit_fenced(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        attempt,
    ) -> HarnessSideEffectOutcome:
        self.fenced_calls += 1
        outcome = self._outcome(intent, authorization)
        if self.persist_before_return:
            return self.store.complete_attempt(attempt, outcome)
        return outcome

    def request_cancellation(self, _attempt) -> None:
        return None

    def confirm_termination(self, _attempt) -> bool:
        return True

    def reconcile(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        _attempt,
    ) -> HarnessSideEffectOutcome | None:
        self.reconcile_calls += 1
        if self.reconcile_barrier is not None:
            self.reconcile_barrier.wait(timeout=5)
        existing = self.store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        return existing or self._outcome(intent, authorization)

    @staticmethod
    def _outcome(
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        return HarnessSideEffectOutcome(
            outcome_id=f"outcome-{intent.effect_id}",
            effect_id=intent.effect_id,
            decision_ref=authorization.checksum,
            run_id=intent.run_id,
            kind=intent.kind,
            handler=authorization.handler,
            idempotency_key=intent.idempotency_key,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            disposition=authorization.disposition,
            candidate_refs=intent.candidate_refs,
            result_ref=checksum_for({"effect_id": intent.effect_id}),
        )


class _ProtocolTrackingFencedHandler:
    def __init__(
        self,
        *,
        clock: _MutableClock | None = None,
        fail_commit: bool = False,
        reconcile_outcome: bool = False,
    ) -> None:
        self.clock = clock
        self.fail_commit = fail_commit
        self.reconcile_outcome = reconcile_outcome
        self.calls: list[str] = []

    def commit(
        self,
        _intent: HarnessSideEffectIntent,
        _authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        raise AssertionError("fenced side-effect must not use serial commit")

    def commit_fenced(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        _attempt,
    ) -> HarnessSideEffectOutcome:
        self.calls.append("commit")
        if self.fail_commit:
            raise RuntimeError("fenced commit failed")
        if self.clock is not None:
            self.clock.advance(31)
        return _FencedEffectHandler._outcome(intent, authorization)

    def request_cancellation(self, _attempt) -> None:
        self.calls.append("cancel")

    def confirm_termination(self, _attempt) -> bool:
        self.calls.append("confirm")
        return True

    def reconcile(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        _attempt,
    ) -> HarnessSideEffectOutcome | None:
        self.calls.append("reconcile")
        if not self.reconcile_outcome:
            return None
        return _FencedEffectHandler._outcome(intent, authorization)


def _parallel_effect_run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=tuple(
            HarnessStepSpec(
                step_id,
                "script",
                output_key=f"{step_id}_output",
                side_effect_handler="parallel.fenced@1",
            )
            for step_id in ("left", "right")
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            graph_id=f"graph-{run_id}",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("left-branch", StepRef("left"), "parallel.left"),
                    ParallelBranch("right-branch", StepRef("right"), "parallel.right"),
                ),
            ),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        metadata={
            "identity_scope_ref": _IDENTITY_SCOPE_REF,
            "subject_scope_ref": _SUBJECT_SCOPE_REF,
        },
        created_at=_CREATED_AT,
    )


def _parallel_effect_worker(worker_calls: list[str]):
    def worker(task: dict) -> HarnessWorkerResult:
        step_id = task["step_id"]
        worker_calls.append(step_id)
        output = {"candidate": step_id}
        candidate = {
            "status": "succeeded",
            "output": output,
            "artifacts": [],
            "diagnostics": {},
            "metrics": {},
            "error": None,
        }
        return HarnessWorkerResult(
            "succeeded",
            output=output,
            effect_intent=HarnessSideEffectIntent(
                effect_id=f"effect-{task['run_id']}-{step_id}",
                kind="artifact",
                run_id=task["run_id"],
                origin="worker",
                atomic_group="parallel-fenced-effects",
                identity_scope_ref=_IDENTITY_SCOPE_REF,
                subject_scope_ref=_SUBJECT_SCOPE_REF,
                attempt=task["harness_activity"]["attempt"],
                step_id=step_id,
                worker_result_ref=harness_worker_candidate_ref(candidate),
                candidate_checksum=checksum_for(output),
                handler="parallel.fenced@1",
            ),
        )

    return worker


def _direct_effect_intent(run_id: str) -> HarnessSideEffectIntent:
    return HarnessSideEffectIntent(
        effect_id=f"effect-{run_id}",
        kind="artifact",
        run_id=run_id,
        origin="worker",
        atomic_group="parallel-fenced-effects",
        identity_scope_ref=_IDENTITY_SCOPE_REF,
        subject_scope_ref=_SUBJECT_SCOPE_REF,
        step_id="left",
        worker_result_ref=checksum_for({"worker": run_id}),
        candidate_checksum=checksum_for({"candidate": run_id}),
        handler="parallel.fenced@1",
    )


def _direct_effect_decision(
    intent: HarnessSideEffectIntent,
    *,
    effect_attempt_limit: int,
) -> HarnessSideEffectDecision:
    return HarnessSideEffectDecision(
        decision_id=f"decision-{intent.effect_id}",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        handler=intent.handler,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=1,
        causation_id=f"event-{intent.effect_id}",
        disposition="prepared",
        step_id=intent.step_id,
        worker_result_ref=intent.worker_result_ref,
        approval_evidence_ref=checksum_for({"approval": intent.effect_id}),
        effect_attempt_limit=effect_attempt_limit,
        decided_at=_CREATED_AT,
    )


def _external_authority(
    worker_ids: tuple[str, ...],
    *,
    side_effect_registry: HarnessSideEffectRegistry | None = None,
) -> HarnessRuntimeBindingAuthority:
    return HarnessRuntimeBindingAuthority(
        workers=tuple(
            HarnessWorkerBinding(
                f"{worker_id}@1",
                "script",
                _ExternalWorker(worker_id),
            )
            for worker_id in worker_ids
        ),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _ParallelSafeActivity(),
            ),
        ),
        side_effect_registry=side_effect_registry,
    )
