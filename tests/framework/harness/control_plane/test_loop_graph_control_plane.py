from datetime import UTC, datetime

import pytest

from framework.harness import (
    DeterministicGate,
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
    HarnessBudget,
    HarnessControlPlane,
    HarnessGateResult,
    HarnessGraphCommitKind,
    HarnessGraphDecisionType,
    HarnessLoopStatus,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.conditions import (
    ConditionAll,
    ConditionAny,
    ConditionPredicate,
)
from framework.harness.graph.dsl import (
    BoundedLoop,
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
)
from framework.harness.graph.validation import HarnessGraphPreflightPolicy
from framework.harness.graph.validation import HarnessGraphPreflight


_CREATED_AT = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)


class _LoopControlFactGate(DeterministicGate):
    gate_name = "loop_control_fact"
    gate_version = "1"

    def evaluate(self, context) -> HarnessGateResult:
        return HarnessGateResult(gate_name=self.gate_name, passed=True)


class _LoopReplanOnceGate(DeterministicGate):
    gate_name = "loop_replan_once"
    gate_version = "1"

    def evaluate(self, context) -> HarnessGateResult:
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=context.step_state.replans > 0,
        )


class _FailAfterLoopBackActivationPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
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
            if (
                decision is not None
                and decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
                and decision.reason_code == "loop_iteration_completed"
            ):
                self.failed = True
                raise RuntimeError("committed loop-back projection response was lost")
        return projected


class _FailAfterBodyTerminalPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
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
            if (
                decision is not None
                and decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
                and decision.node_id == "body"
            ):
                self.failed = True
                raise RuntimeError(
                    "committed body terminal projection response was lost"
                )
        return projected


def test_bounded_loop_uses_distinct_instances_and_exact_exhaustion_bound() -> None:
    run_spec = _loop_run_spec("run-loop-exhaustion", max_iterations=2)
    port = InMemoryHarnessEventPort()
    worker_calls: list[str] = []

    result = _control_plane(port, worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["body", "body", "exhausted"]
    counter = result.graph_state.loop_counters[0]
    assert counter.completed_iterations == 2
    assert counter.max_iterations == 2
    assert counter.status is HarnessLoopStatus.EXHAUSTED
    bodies = tuple(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    assert len(bodies) == 2
    assert [item.identity.iteration_vector[-1].iteration for item in bodies] == [0, 1]
    assert [item.attempt for item in bodies] == [1, 1]
    assert len({item.instance_id for item in bodies}) == 2


def test_loop_iterations_keep_output_and_evidence_scopes_separate() -> None:
    run_spec = _loop_run_spec("run-loop-output-scopes", max_iterations=2)
    body_call = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal body_call
        if task["step_id"] == "body":
            body_call += 1
        return HarnessWorkerResult(
            "succeeded",
            output={"body_call": body_call, "step": task["step_id"]},
        )

    result = _control_plane_with_worker(InMemoryHarnessEventPort(), worker).run(
        run_spec
    )

    assert result.graph_state is not None
    bodies = tuple(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    assert len(bodies) == 2
    assert len({item.output_refs["activity_result"] for item in bodies}) == 2
    assert all(
        evidence.node_instance_id == body.instance_id
        for body in bodies
        for evidence in body.evidence_refs
    )
    assert {item.event_sequence for item in bodies[0].evidence_refs}.isdisjoint(
        item.event_sequence for item in bodies[1].evidence_refs
    )


def test_bounded_loop_false_condition_exits_without_body_activation() -> None:
    run_spec = _loop_run_spec(
        "run-loop-exit",
        max_iterations=2,
        should_continue=False,
        include_exhaustion=False,
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["exit"]
    counter = result.graph_state.loop_counters[0]
    assert counter.completed_iterations == 0
    assert counter.status is HarnessLoopStatus.EXITED
    assert all(
        item.identity.node_id != "body" for item in result.graph_state.node_instances
    )


def test_retry_stays_in_one_loop_iteration_and_one_node_instance() -> None:
    run_spec = _loop_run_spec(
        "run-loop-retry",
        max_iterations=1,
        body_retry_attempts=2,
    )
    port = InMemoryHarnessEventPort()
    calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal calls
        if task["step_id"] != "body":
            return HarnessWorkerResult(
                "succeeded",
                output={"step": task["step_id"]},
            )
        calls += 1
        if calls == 1:
            return HarnessWorkerResult("failed", error="retry")
        return HarnessWorkerResult("succeeded", output={"body": "accepted"})

    result = _control_plane_with_worker(port, worker).run(run_spec)

    assert result.graph_state is not None
    bodies = tuple(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    assert len(bodies) == 1
    assert bodies[0].identity.iteration_vector[-1].iteration == 0
    assert bodies[0].attempt == 2
    assert result.graph_state.loop_counters[0].completed_iterations == 1
    assert calls == 2


def test_run_worker_budget_stops_loop_before_another_worker_call() -> None:
    run_spec = _loop_run_spec(
        "run-loop-global-budget",
        max_iterations=3,
        budget=HarnessBudget(
            max_turns=30,
            max_replans=0,
            max_retries_per_step=0,
            max_worker_calls=1,
        ),
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.HALTED
    assert worker_calls == ["body"]
    assert result.graph_state.loop_counters[0].completed_iterations == 1
    assert result.graph_state.budgets.require("worker_calls").used == 1


def test_run_turn_budget_is_shared_across_loop_iterations() -> None:
    run_spec = _loop_run_spec(
        "run-loop-turn-budget",
        max_iterations=3,
        budget=HarnessBudget(
            max_turns=3,
            max_replans=0,
            max_retries_per_step=0,
            max_worker_calls=10,
        ),
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.HALTED
    assert result.graph_state.terminal_reason_code == "turn_budget_exhausted"
    assert worker_calls == ["body"]
    assert result.graph_state.loop_counters[0].completed_iterations == 1
    assert result.graph_state.budgets.require("turns").used == 3


def test_retry_budget_usage_accumulates_across_loop_iterations() -> None:
    run_spec = _loop_run_spec(
        "run-loop-retry-budget",
        max_iterations=2,
        body_retry_attempts=2,
        budget=HarnessBudget(
            max_turns=30,
            max_replans=0,
            max_retries_per_step=1,
            max_worker_calls=10,
        ),
    )
    worker_calls: list[str] = []
    body_calls = 0

    def worker(task: dict) -> HarnessWorkerResult:
        nonlocal body_calls
        worker_calls.append(task["step_id"])
        if task["step_id"] == "body":
            body_calls += 1
            if body_calls % 2 == 1:
                return HarnessWorkerResult("failed", error="retry")
        return HarnessWorkerResult("succeeded", output={"call": body_calls})

    result = _control_plane_with_worker(InMemoryHarnessEventPort(), worker).run(
        run_spec
    )

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["body", "body", "body", "body", "exhausted"]
    bodies = tuple(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    assert [item.attempt for item in bodies] == [2, 2]
    assert result.graph_state.budgets.require("retries").used == 2


def test_retry_bound_fails_loop_before_another_iteration() -> None:
    run_spec = _loop_run_spec(
        "run-loop-retry-bound",
        max_iterations=2,
        body_retry_attempts=3,
        budget=HarnessBudget(
            max_turns=30,
            max_replans=0,
            max_retries_per_step=1,
            max_worker_calls=10,
        ),
    )
    worker_calls: list[str] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("failed", error="retry")

    result = _control_plane_with_worker(InMemoryHarnessEventPort(), worker).run(
        run_spec
    )

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.COMPLETED
    assert result.graph_state.outcome is RunOutcome.FAILED
    assert worker_calls == ["body", "body"]
    body = next(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    assert body.attempt == 2
    assert result.graph_state.budgets.require("retries").used == 1
    assert result.graph_state.loop_counters[0].completed_iterations == 0
    assert result.graph_state.loop_counters[0].status is HarnessLoopStatus.EXITED


def test_replan_budget_stops_a_later_loop_iteration() -> None:
    run_spec = _loop_run_spec(
        "run-loop-replan-budget",
        max_iterations=2,
        body_quality_gate="loop_replan_once@1",
        budget=HarnessBudget(
            max_turns=30,
            max_replans=1,
            max_retries_per_step=0,
            max_worker_calls=10,
        ),
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.HALTED
    assert result.graph_state.terminal_reason_code == (
        "verification_failed_replans_exhausted"
    )
    assert worker_calls == ["body", "body", "body"]
    bodies = tuple(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    assert [item.replans for item in bodies] == [1, 0]
    assert result.graph_state.loop_counters[0].completed_iterations == 1
    assert result.graph_state.budgets.require("replans").used == 1


def test_loop_activation_budget_is_cumulative_and_preflight_bounded() -> None:
    accepted_spec = _loop_run_spec("run-loop-activation-budget", max_iterations=2)
    accepted_calls: list[str] = []

    accepted = _control_plane_with_worker(
        InMemoryHarnessEventPort(),
        _recording_worker(accepted_calls),
        max_node_activations=8,
    ).run(accepted_spec)

    assert accepted.graph_state is not None
    activation_budget = accepted.graph_state.budgets.require("node_activations")
    assert activation_budget.limit == 8
    assert activation_budget.used == 7

    rejected_calls: list[str] = []
    rejected_spec = _loop_run_spec(
        "run-loop-activation-budget-rejected",
        max_iterations=2,
    )
    with pytest.raises(HarnessValidationError) as captured:
        _control_plane_with_worker(
            InMemoryHarnessEventPort(),
            _recording_worker(rejected_calls),
            max_node_activations=7,
        ).run(rejected_spec)

    assert captured.value.code == "harness_graph_preflight_failed"
    assert captured.value.details["diagnostics"][0]["code"] == (
        "graph_activation_limit_exceeded"
    )
    assert rejected_calls == []


def test_loop_recovers_committed_loop_back_without_repeating_iteration() -> None:
    run_spec = _loop_run_spec("run-loop-recovery", max_iterations=2)
    port = _FailAfterLoopBackActivationPort()
    worker_calls: list[str] = []

    with pytest.raises(RuntimeError, match="loop-back projection response was lost"):
        _control_plane(port, worker_calls).run(run_spec)

    result = _control_plane(port, worker_calls).recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["body", "body", "exhausted"]
    recovery = port.recover_graph(run_spec.run_id)
    loop_back_activations = tuple(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
        and item.decision.reason_code == "loop_iteration_completed"
    )
    assert len(loop_back_activations) == 2


def test_loop_recovers_committed_body_terminal_without_repeating_worker() -> None:
    run_spec = _loop_run_spec("run-loop-body-terminal-recovery", max_iterations=2)
    port = _FailAfterBodyTerminalPort()
    worker_calls: list[str] = []

    with pytest.raises(
        RuntimeError,
        match="committed body terminal projection response was lost",
    ):
        _control_plane(port, worker_calls).run(run_spec)

    result = _control_plane(port, worker_calls).recover_and_run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["body", "body", "exhausted"]
    assert result.graph_state.loop_counters[0].completed_iterations == 2
    recovery = port.recover_graph(run_spec.run_id)
    body_completions = tuple(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
        and item.decision.node_id == "body"
    )
    assert len(body_completions) == 2


def test_nested_parallel_loop_preserves_branch_and_iteration_scope() -> None:
    loop = BoundedLoop(
        "loop",
        StepRef("body"),
        ConditionPredicate("graph.inputs.continue", "equals", True),
        1,
        exit=StepRef("exit"),
        exhaustion=StepRef("exhausted"),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="nested-parallel-loop",
        steps=tuple(
            HarnessStepSpec(step_id, "script")
            for step_id in ("body", "exit", "exhausted", "sibling")
        ),
        entry_step_id="body",
        graph=HarnessGraphSpec(
            "nested-parallel-loop",
            ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("loop-branch", loop, "parallel.loop"),
                    ParallelBranch(
                        "sibling-branch",
                        StepRef("sibling"),
                        "parallel.sibling",
                    ),
                ),
            ),
        ),
    )
    run_spec = HarnessRunSpec(
        "run-nested-parallel-loop",
        workflow,
        inputs={"continue": True},
        created_at=_CREATED_AT,
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    body = next(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "body"
    )
    counter = result.graph_state.loop_counters[0]
    assert body.identity.branch_path == ("loop-branch",)
    assert body.identity.iteration_vector[-1].iteration == 0
    assert counter.branch_path == ("loop-branch",)
    assert counter.completed_iterations == 1
    assert set(result.graph_state.join_states[0].completed_branch_instances) == {
        "loop-branch",
        "sibling-branch",
    }


def test_loop_body_parallel_branches_inherit_iteration_scope() -> None:
    parallel_body = ParallelAll(
        "fork",
        "join",
        (
            ParallelBranch("left-branch", StepRef("left"), "loop.left"),
            ParallelBranch("right-branch", StepRef("right"), "loop.right"),
        ),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="loop-parallel-body",
        steps=tuple(
            HarnessStepSpec(step_id, "script")
            for step_id in ("left", "right", "exit", "exhausted")
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            "loop-parallel-body",
            BoundedLoop(
                "loop",
                parallel_body,
                ConditionPredicate("graph.inputs.continue", "equals", True),
                1,
                exit=StepRef("exit"),
                exhaustion=StepRef("exhausted"),
            ),
        ),
    )
    run_spec = HarnessRunSpec(
        "run-loop-parallel-body",
        workflow,
        inputs={"continue": True},
        created_at=_CREATED_AT,
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["left", "right", "exhausted"]
    branches = tuple(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id in {"left", "right"}
    )
    assert {item.identity.branch_path for item in branches} == {
        ("left-branch",),
        ("right-branch",),
    }
    assert all(
        item.identity.iteration_vector[-1].loop_id == "loop"
        and item.identity.iteration_vector[-1].iteration == 0
        for item in branches
    )
    join = result.graph_state.join_states[0]
    assert set(join.completed_branch_instances) == {"left-branch", "right-branch"}
    assert result.graph_state.loop_counters[0].completed_iterations == 1


def test_loop_condition_reads_upstream_and_prior_iteration_sources() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="loop-condition-sources",
        steps=tuple(
            HarnessStepSpec(
                step_id,
                "script",
                output_key=f"{step_id}_output",
                quality_gate=(
                    "loop_control_fact@1" if step_id in {"seed", "body"} else None
                ),
                metadata=(
                    {"control_fact_paths": ["continue"]}
                    if step_id in {"seed", "body"}
                    else {}
                ),
            )
            for step_id in ("seed", "body", "exit")
        ),
        entry_step_id="seed",
        graph=HarnessGraphSpec(
            "loop-condition-sources",
            Sequence(
                (
                    StepRef("seed"),
                    BoundedLoop(
                        "loop",
                        StepRef("body"),
                        ConditionAll(
                            (
                                ConditionPredicate(
                                    "graph.inputs.enabled",
                                    "equals",
                                    True,
                                ),
                                ConditionAny(
                                    (
                                        ConditionPredicate(
                                            "node.outputs.continue",
                                            "equals",
                                            True,
                                        ),
                                        ConditionPredicate(
                                            "graph.inputs.force_continue",
                                            "equals",
                                            True,
                                        ),
                                    )
                                ),
                            )
                        ),
                        3,
                        exit=StepRef("exit"),
                    ),
                )
            ),
        ),
    )
    run_spec = HarnessRunSpec(
        "run-loop-condition-sources",
        workflow,
        inputs={"enabled": True, "force_continue": False},
        created_at=_CREATED_AT,
    )
    worker_calls: list[str] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult(
            "succeeded",
            output={"continue": task["step_id"] == "seed"},
        )

    result = _control_plane_with_worker(InMemoryHarnessEventPort(), worker).run(
        run_spec
    )

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert worker_calls == ["seed", "body", "exit"]
    assert result.graph_state.loop_counters[0].completed_iterations == 1
    assert result.graph_state.loop_counters[0].status is HarnessLoopStatus.EXITED


def test_loop_true_at_bound_without_exhaustion_halts_typed() -> None:
    run_spec = _loop_run_spec(
        "run-loop-bound-halt",
        max_iterations=1,
        include_exhaustion=False,
    )
    worker_calls: list[str] = []

    result = _control_plane(InMemoryHarnessEventPort(), worker_calls).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.lifecycle is RunLifecycle.HALTED
    assert result.graph_state.terminal_reason_code == "loop_budget_exhausted"
    assert worker_calls == ["body"]


def _loop_run_spec(
    run_id: str,
    *,
    max_iterations: int,
    should_continue: bool = True,
    include_exhaustion: bool = True,
    body_retry_attempts: int = 1,
    body_quality_gate: str | None = None,
    budget: HarnessBudget | None = None,
) -> HarnessRunSpec:
    step_ids = ["body", "exit"]
    if include_exhaustion:
        step_ids.append("exhausted")
    steps = tuple(
        HarnessStepSpec(
            step_id,
            "script",
            retry_policy=(
                HarnessRetryPolicy(max_attempts=body_retry_attempts)
                if step_id == "body"
                else HarnessRetryPolicy()
            ),
            quality_gate=(body_quality_gate if step_id == "body" else None),
        )
        for step_id in step_ids
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=steps,
        entry_step_id="body",
        graph=HarnessGraphSpec(
            f"graph-{run_id}",
            BoundedLoop(
                "loop",
                StepRef("body"),
                ConditionPredicate("graph.inputs.continue", "equals", True),
                max_iterations,
                exit=StepRef("exit"),
                exhaustion=(StepRef("exhausted") if include_exhaustion else None),
            ),
        ),
    )
    return HarnessRunSpec(
        run_id,
        workflow,
        inputs={"continue": should_continue},
        budget=budget or HarnessBudget.safe_default(),
        created_at=_CREATED_AT,
    )


def _control_plane(
    port: InMemoryHarnessEventPort,
    worker_calls: list[str],
) -> HarnessControlPlane:
    return _control_plane_with_worker(port, _recording_worker(worker_calls))


def _recording_worker(worker_calls: list[str]):
    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task["step_id"])
        return HarnessWorkerResult("succeeded", output={"step": task["step_id"]})

    return worker


def _control_plane_with_worker(
    port,
    worker,
    *,
    max_node_activations: int = 40,
) -> HarnessControlPlane:
    gates = (_LoopControlFactGate(), _LoopReplanOnceGate())
    return HarnessControlPlane(
        event_port=port,
        worker_registry={
            step_id: worker
            for step_id in (
                "seed",
                "body",
                "exit",
                "exhausted",
                "sibling",
                "left",
                "right",
            )
        },
        gate_registry=DeterministicGateRegistry(
            tuple(
                GateRegistration(
                    GateReference(gate.gate_name, gate.gate_version),
                    gate,
                )
                for gate in gates
            )
        ),
        graph_preflight=HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(
                max_node_activations=max_node_activations,
                max_active_nodes=6,
                max_parallelism=1,
            )
        ),
    )
