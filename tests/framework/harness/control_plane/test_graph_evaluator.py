from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphCandidateType,
    HarnessGraphEvaluationContext,
    HarnessGraphObservationType,
    HarnessGraphEvaluator,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphDecisionApplier,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import (
    HarnessAttemptEvidenceReference,
    HarnessBudgetCounterState,
    HarnessCompensationEntry,
    HarnessCompensationStatus,
    HarnessEvidenceKind,
    HarnessGraphBudgetState,
    HarnessGraphState,
    HarnessJoinState,
    HarnessLoopCounterState,
    HarnessLoopIteration,
    HarnessNodeInstanceIdentity,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
    HarnessWaitRegistration,
)
from framework.harness.control_plane.scheduler import HarnessScheduler
from framework.harness.control_plane.state import HarnessStepStatus
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.conditions import ConditionPredicate
from framework.harness.graph.dsl import (
    BoundedLoop,
    Choice,
    ChoiceBranch,
    CompensationBinding,
    HarnessGraphSpec,
    ParallelAll,
    ParallelAny,
    ParallelBranch,
    Sequence,
    StepRef,
    Wait,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec


def test_sequence_entry_and_successor_readiness_are_deterministic() -> None:
    graph = _compile(
        Sequence((StepRef("collect"), StepRef("analyze"))),
        "collect",
        "analyze",
    )
    evaluator = HarnessGraphEvaluator()

    initial = evaluator.evaluate(graph, _state(graph))
    collect = _node(graph, "collect", "succeeded", ordinal=0, sequence=2)
    after_collect = evaluator.evaluate(graph, _state(graph, nodes=(collect,)))
    repeated = evaluator.evaluate(graph, _state(graph, nodes=(collect,)))

    assert _candidate_types(initial) == (HarnessGraphCandidateType.ACTIVATE_NODE,)
    assert initial.candidates[0].node_id == "collect"
    assert _candidate_types(after_collect) == (HarnessGraphCandidateType.ACTIVATE_NODE,)
    assert after_collect.candidates[0].node_id == "analyze"
    assert after_collect.to_dict() == repeated.to_dict()


def test_choice_uses_stable_priority_and_ignores_worker_shaped_suggestions() -> None:
    graph = _compile(
        Choice(
            "route",
            (
                ChoiceBranch(
                    "fallback",
                    StepRef("fallback"),
                    20,
                    is_default=True,
                ),
                ChoiceBranch(
                    "primary",
                    StepRef("primary"),
                    10,
                    condition=ConditionPredicate(
                        "graph.inputs.kind",
                        "equals",
                        "primary",
                    ),
                ),
            ),
        ),
        "primary",
        "fallback",
    )
    choice = _node(graph, "route", "ready", ordinal=0, sequence=1)
    context = HarnessGraphEvaluationContext(inputs={"kind": "primary"})

    evaluation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(choice,)),
        context=context,
    )

    selected = evaluation.candidates[0]
    assert selected.candidate_type is HarnessGraphCandidateType.SELECT_CHOICE
    assert selected.branch_id == "primary"
    assert selected.target_node_ids == ("primary",)
    assert selected.payload["branch_priority"] == 10


def test_choice_without_match_or_default_halts_with_typed_reason() -> None:
    graph = _compile(
        Choice(
            "route",
            (
                ChoiceBranch(
                    "only",
                    StepRef("target"),
                    1,
                    condition=ConditionPredicate(
                        "graph.inputs.allowed",
                        "equals",
                        True,
                    ),
                ),
            ),
        ),
        "target",
    )
    choice = _node(graph, "route", "ready", ordinal=0, sequence=1)

    candidate = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(choice,)),
            context=HarnessGraphEvaluationContext(inputs={"allowed": False}),
        )
        .candidates[0]
    )

    assert candidate.candidate_type is HarnessGraphCandidateType.HALT_RUN
    assert candidate.reason_code == "no_matching_route"


def test_committed_choice_selection_precedes_target_activation() -> None:
    graph = _compile(
        Choice(
            "route",
            (
                ChoiceBranch(
                    "selected",
                    StepRef("target"),
                    1,
                    is_default=True,
                ),
            ),
        ),
        "target",
    )
    selected = _node(
        graph,
        "route",
        "succeeded",
        ordinal=0,
        sequence=2,
        metadata={"selected_branch_id": "selected"},
    )

    candidate = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(selected,)),
        )
        .candidates[0]
    )

    assert candidate.candidate_type is HarnessGraphCandidateType.ACTIVATE_NODE
    assert candidate.node_id == "target"
    assert candidate.branch_id == "selected"
    assert candidate.payload["source_node_instance_id"] == selected.instance_id


def test_parallel_all_fork_and_join_facts_are_explicit() -> None:
    graph = _compile(
        ParallelAll(
            "fork",
            "join",
            (
                ParallelBranch("left", StepRef("left"), "parallel.left"),
                ParallelBranch("right", StepRef("right"), "parallel.right"),
            ),
        ),
        "left",
        "right",
    )
    fork_ready = _node(graph, "fork", "ready", ordinal=0, sequence=1)
    opened = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(fork_ready,)),
        )
        .candidates[0]
    )

    assert opened.candidate_type is HarnessGraphCandidateType.OPEN_FORK
    assert opened.target_node_ids == ("left", "right")
    assert opened.payload["join_node_id"] == "join"

    fork = _node(graph, "fork", "succeeded", ordinal=0, sequence=1)
    left = _node(
        graph,
        "left",
        "succeeded",
        ordinal=1,
        sequence=3,
        branch_path=("left",),
    )
    right = _node(
        graph,
        "right",
        "succeeded",
        ordinal=2,
        sequence=4,
        branch_path=("right",),
    )
    join = _node(graph, "join", "running", ordinal=3, sequence=5)
    join_state = HarnessJoinState(
        join.instance_id,
        fork.instance_id,
        "all",
        "open",
        ("left", "right"),
        {"left": left.instance_id, "right": right.instance_id},
        {"left": _sha("left-terminal"), "right": _sha("right-terminal")},
        last_event_sequence=5,
    )

    satisfied = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(
                graph,
                nodes=(join, right, fork, left),
                joins=(join_state,),
            ),
        )
        .candidates[0]
    )

    assert satisfied.candidate_type is HarnessGraphCandidateType.SATISFY_JOIN
    assert satisfied.evidence_refs == tuple(
        sorted((_sha("left-terminal"), _sha("right-terminal")))
    )


def test_parallel_any_winner_uses_lowest_durable_terminal_sequence() -> None:
    graph = _compile(
        ParallelAny(
            "fork",
            "join",
            (
                ParallelBranch("slow", StepRef("slow"), "parallel.slow"),
                ParallelBranch("fast", StepRef("fast"), "parallel.fast"),
            ),
        ),
        "slow",
        "fast",
    )
    fork = _node(graph, "fork", "succeeded", ordinal=0, sequence=1)
    slow = _node(
        graph,
        "slow",
        "succeeded",
        ordinal=1,
        sequence=8,
        branch_path=("slow",),
    )
    fast = _node(
        graph,
        "fast",
        "succeeded",
        ordinal=2,
        sequence=6,
        branch_path=("fast",),
    )
    join = _node(graph, "join", "running", ordinal=3, sequence=9)
    join_state = HarnessJoinState(
        join.instance_id,
        fork.instance_id,
        "any",
        "open",
        ("slow", "fast"),
        {"slow": slow.instance_id, "fast": fast.instance_id},
        {"slow": _sha("slow-terminal"), "fast": _sha("fast-terminal")},
        last_event_sequence=9,
    )

    winner = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(slow, join, fast, fork), joins=(join_state,)),
        )
        .candidates[0]
    )

    assert winner.candidate_type is HarnessGraphCandidateType.SELECT_PARALLEL_WINNER
    assert winner.branch_id == "fast"
    assert winner.payload["winner_node_instance_id"] == fast.instance_id
    assert winner.evidence_refs == (_sha("fast-terminal"),)


@pytest.mark.parametrize(
    ("continue_value", "completed", "candidate_type", "target"),
    (
        (True, 0, HarnessGraphCandidateType.START_LOOP_ITERATION, "body"),
        (False, 0, HarnessGraphCandidateType.EXIT_LOOP, "exit"),
        (True, 2, HarnessGraphCandidateType.EXHAUST_LOOP, "exhausted"),
    ),
)
def test_bounded_loop_produces_continue_exit_and_exhaustion_facts(
    continue_value: bool,
    completed: int,
    candidate_type: HarnessGraphCandidateType,
    target: str,
) -> None:
    graph = _compile(
        BoundedLoop(
            "loop",
            StepRef("body"),
            ConditionPredicate("graph.inputs.continue", "equals", True),
            2,
            exit=StepRef("exit"),
            exhaustion=StepRef("exhausted"),
        ),
        "body",
        "exit",
        "exhausted",
    )
    guard = _node(graph, "loop", "ready", ordinal=0, sequence=1)
    counter = HarnessLoopCounterState(
        "loop",
        (),
        (),
        completed,
        2,
        "exhausted" if completed == 2 else "active",
        1,
    )

    candidate = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(guard,), loops=(counter,)),
            context=HarnessGraphEvaluationContext(inputs={"continue": continue_value}),
        )
        .candidates[0]
    )

    assert candidate.candidate_type is candidate_type
    assert candidate.target_node_ids == (target,)


def test_wait_registration_resume_and_run_waiting_projection_are_separate() -> None:
    graph = _compile(
        Wait(
            "approval",
            "approval",
            {"path": "graph.inputs.request_id"},
            "editor.approval",
            "1",
            "graph.inputs.tenant_id",
            "graph.inputs.actor_id",
        )
    )
    ready = _node(graph, "approval", "ready", ordinal=0, sequence=1)
    registration_candidate = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(ready,)),
        )
        .candidates[0]
    )

    assert (
        registration_candidate.candidate_type is HarnessGraphCandidateType.REGISTER_WAIT
    )

    waiting = _node(graph, "approval", "waiting", ordinal=0, sequence=2)
    registered = _wait_registration(waiting.instance_id, "registered", sequence=2)
    waiting_candidate = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(waiting,), waits=(registered,)),
        )
        .candidates[0]
    )
    assert (
        waiting_candidate.candidate_type
        is HarnessGraphCandidateType.PROJECT_RUN_WAITING
    )

    resumed = _wait_registration(waiting.instance_id, "resumed", sequence=2)
    resume_candidate = (
        HarnessGraphEvaluator()
        .evaluate(
            graph,
            _state(graph, nodes=(waiting,), waits=(resumed,)),
        )
        .candidates[0]
    )
    assert resume_candidate.candidate_type is HarnessGraphCandidateType.RESUME_WAIT
    assert resume_candidate.evidence_refs == (_sha("wait-resolution"),)


def test_compensation_progress_selects_reverse_durable_effect_order() -> None:
    graph, state, earlier, later = _compensation_state()

    candidate = (
        HarnessGraphEvaluator()
        .evaluate(graph, state)
        .candidates[0]
    )

    assert candidate.candidate_type is HarnessGraphCandidateType.SCHEDULE_COMPENSATION
    assert candidate.node_id == "compensation:undo-publish"
    assert candidate.payload["entry_id"] == later.entry_id
    assert candidate.evidence_refs == (later.effect_outcome_ref,)
    assert earlier.effect_commit_sequence < later.effect_commit_sequence


def test_compensation_schedule_atomically_projects_selected_entry_and_instance() -> (
    None
):
    graph, state, earlier, later = _compensation_state()
    decision = HarnessScheduler().next_decision(state, graph=graph)

    assert decision is not None
    assert decision.decision_type.value == "schedule_compensation"
    applied = HarnessGraphDecisionApplier().apply(
        state,
        graph,
        decision,
        decision_sequence=state.last_event_sequence + 1,
        projection_sequence=state.last_event_sequence + 2,
    ).state

    entries = {item.entry_id: item for item in applied.compensation_stack}
    assert entries[earlier.entry_id].status is HarnessCompensationStatus.PENDING
    running = entries[later.entry_id]
    assert running.status is HarnessCompensationStatus.RUNNING
    assert running.compensation_node_instance_id is not None
    compensation = next(
        item
        for item in applied.node_instances
        if item.instance_id == running.compensation_node_instance_id
    )
    assert compensation.identity.node_id == "compensation:undo-publish"
    assert compensation.status is HarnessNodeInstanceStatus.COMPENSATING
    assert compensation.step_status is HarnessStepStatus.PENDING
    assert compensation.metadata["compensation_entry_id"] == later.entry_id
    assert compensation.metadata["effect_outcome_ref"] == later.effect_outcome_ref
    assert applied.budgets.require("node_activations").used == 1
    assert applied.budgets.require("compensations").used == 1
    assert HarnessGraphEvaluator().evaluate(graph, applied).candidates == ()


def test_compensation_budget_exhaustion_halts_before_scheduling() -> None:
    graph, state, earlier, later = _compensation_state()
    budgets = HarnessGraphBudgetState(
        tuple(
            replace(counter, used=counter.limit)
            if counter.name == "compensations"
            else counter
            for counter in state.budgets.counters
        )
    )
    exhausted = replace(state, budgets=budgets, projection_checksum=None)

    evaluation = HarnessGraphEvaluator().evaluate(graph, exhausted)

    assert _candidate_types(evaluation) == (HarnessGraphCandidateType.HALT_RUN,)
    candidate = evaluation.candidates[0]
    assert candidate.reason_code == "compensation_budget_exhausted"
    assert candidate.evidence_refs == (
        earlier.effect_outcome_ref,
        later.effect_outcome_ref,
    )


def test_graph_completion_uses_terminal_projection_without_live_activity() -> None:
    graph = _compile(StepRef("done"), "done")
    terminal = _node(graph, "done", "succeeded", ordinal=0, sequence=2)

    evaluation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(terminal,)),
    )

    assert _candidate_types(evaluation) == (HarnessGraphCandidateType.COMPLETE_RUN,)
    assert evaluation.candidates[0].reason_code == "graph_terminal_nodes_succeeded"
    assert evaluation.candidates[0].payload["outcome"] == "succeeded"


def test_evaluation_is_stable_under_state_input_permutation() -> None:
    graph = _compile(
        Sequence((StepRef("first"), StepRef("second"))),
        "first",
        "second",
    )
    first = _node(graph, "first", "succeeded", ordinal=0, sequence=2)
    unrelated = _node(graph, "second", "pending", ordinal=1, sequence=3)
    one = _state(graph, nodes=(first, unrelated))
    two = _state(graph, nodes=(unrelated, first))

    first_eval = HarnessGraphEvaluator().evaluate(graph, one)
    second_eval = HarnessGraphEvaluator().evaluate(graph, two)

    assert one.projection_checksum == two.projection_checksum
    assert first_eval.to_dict() == second_eval.to_dict()


def test_parallel_all_failure_is_stable_under_join_mapping_permutation() -> None:
    graph = _compile(
        ParallelAll(
            "fork",
            "join",
            (
                ParallelBranch("left", StepRef("left"), "parallel.left"),
                ParallelBranch("right", StepRef("right"), "parallel.right"),
            ),
        ),
        "left",
        "right",
    )
    fork = _node(graph, "fork", "succeeded", ordinal=0, sequence=1)
    left = _node(
        graph,
        "left",
        "failed",
        ordinal=1,
        sequence=3,
        branch_path=("left",),
    )
    right = _node(
        graph,
        "right",
        "failed",
        ordinal=2,
        sequence=4,
        branch_path=("right",),
    )
    join = _node(graph, "join", "running", ordinal=3, sequence=5)

    def evaluation(reverse: bool):
        instances = (
            {"right": right.instance_id, "left": left.instance_id}
            if reverse
            else {"left": left.instance_id, "right": right.instance_id}
        )
        evidence = (
            {"right": _sha("right-terminal"), "left": _sha("left-terminal")}
            if reverse
            else {"left": _sha("left-terminal"), "right": _sha("right-terminal")}
        )
        join_state = HarnessJoinState(
            join.instance_id,
            fork.instance_id,
            "all",
            "open",
            ("left", "right"),
            instances,
            evidence,
            last_event_sequence=5,
        )
        state = _state(
            graph,
            nodes=(fork, left, right, join),
            joins=(join_state,),
        )
        return state, HarnessGraphEvaluator().evaluate(graph, state)

    first_state, first = evaluation(False)
    second_state, second = evaluation(True)

    assert first_state.projection_checksum == second_state.projection_checksum
    assert first.to_dict() == second.to_dict()
    assert first.candidates[0].payload["failed_branch_ids"] == ("left", "right")


def test_sequence_readiness_is_isolated_per_loop_iteration_scope() -> None:
    graph = _compile(
        BoundedLoop(
            "loop",
            Sequence((StepRef("first"), StepRef("second"))),
            ConditionPredicate("graph.inputs.continue", "equals", True),
            2,
            exit=StepRef("exit"),
        ),
        "first",
        "second",
        "exit",
    )
    iteration_zero = (HarnessLoopIteration("loop", 0),)
    iteration_one = (HarnessLoopIteration("loop", 1),)
    guard = _node(graph, "loop", "succeeded", ordinal=0, sequence=1)
    first_zero = _node(
        graph,
        "first",
        "succeeded",
        ordinal=1,
        sequence=2,
        iteration_vector=iteration_zero,
    )
    second_zero = _node(
        graph,
        "second",
        "succeeded",
        ordinal=2,
        sequence=3,
        iteration_vector=iteration_zero,
    )
    first_one = _node(
        graph,
        "first",
        "succeeded",
        ordinal=3,
        sequence=4,
        iteration_vector=iteration_one,
    )
    counter = HarnessLoopCounterState("loop", (), (), 1, 2, "active", 4)

    evaluation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(
            graph,
            nodes=(guard, first_zero, second_zero, first_one),
            loops=(counter,),
        ),
    )

    candidates = tuple(
        item
        for item in evaluation.candidates
        if item.candidate_type is HarnessGraphCandidateType.ACTIVATE_NODE
    )
    assert len(candidates) == 1
    assert candidates[0].node_id == "second"
    assert candidates[0].payload["iteration_vector"] == (
        {"loop_id": "loop", "iteration": 1},
    )


def test_choice_reads_only_durable_attempt_bound_observations() -> None:
    graph = _compile(
        Sequence(
            (
                StepRef("source"),
                Choice(
                    "route",
                    (
                        ChoiceBranch(
                            "accepted",
                            StepRef("accepted"),
                            1,
                            condition=ConditionPredicate(
                                "worker_result.status",
                                "equals",
                                "succeeded",
                            ),
                        ),
                    ),
                ),
            )
        ),
        "source",
        "accepted",
    )
    source_identity = _identity(graph, "source", ordinal=0)
    definition = next(item for item in graph.nodes if item.node_id == "source")
    assert isinstance(definition, HarnessExecutableNode)
    worker_payload = {"status": "succeeded"}
    evidence = HarnessAttemptEvidenceReference(
        _sha("source-result"),
        HarnessEvidenceKind.ACTIVITY_RESULT,
        source_identity.instance_id,
        1,
        2,
        contract_ref=definition.worker_ref,
        payload_ref=canonical_checksum(worker_payload),
    )
    source = _node(
        graph,
        "source",
        "succeeded",
        ordinal=0,
        sequence=2,
        evidence=(evidence,),
    )
    choice = _node(graph, "route", "ready", ordinal=1, sequence=3)
    observation = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.WORKER_STATUS,
        "source",
        source.instance_id,
        1,
        2,
        definition.worker_ref,
        evidence.evidence_ref,
        worker_payload,
    )
    state = _state(graph, nodes=(source, choice))

    selected = HarnessGraphEvaluator().evaluate(
        graph,
        state,
        context=HarnessGraphEvaluationContext(observations=(observation,)),
    )
    assert selected.candidates[0].branch_id == "accepted"

    with pytest.raises(HarnessValidationError) as stale_attempt:
        HarnessGraphEvaluator().evaluate(
            graph,
            state,
            context=HarnessGraphEvaluationContext(
                observations=(replace(observation, attempt=2),)
            ),
        )
    assert stale_attempt.value.code == "cross_attempt_graph_observation_rejected"


def test_choice_converges_through_selected_branch_before_common_successor() -> None:
    graph = _compile(
        Sequence(
            (
                Choice(
                    "route",
                    (
                        ChoiceBranch(
                            "left",
                            StepRef("left"),
                            0,
                            is_default=True,
                        ),
                        ChoiceBranch(
                            "right",
                            StepRef("right"),
                            1,
                            condition=ConditionPredicate(
                                "graph.inputs.route",
                                "equals",
                                "right",
                            ),
                        ),
                    ),
                ),
                StepRef("after"),
            )
        ),
        "left",
        "right",
        "after",
    )
    choice = _node(
        graph,
        "route",
        "succeeded",
        ordinal=0,
        sequence=1,
        metadata={"selected_branch_id": "left"},
    )
    left = _node(
        graph,
        "left",
        "succeeded",
        ordinal=1,
        sequence=2,
        branch_path=("left",),
    )

    join_activation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(choice, left)),
    )
    assert _candidate_types(join_activation) == (
        HarnessGraphCandidateType.ACTIVATE_NODE,
    )
    assert join_activation.candidates[0].node_id == "route:join"
    assert join_activation.candidates[0].payload["branch_path"] == ()
    assert join_activation.candidates[0].payload["selected_branch_id"] == "left"

    join = _node(
        graph,
        "route:join",
        "succeeded",
        ordinal=2,
        sequence=3,
    )
    successor = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(choice, left, join)),
    )
    assert _candidate_types(successor) == (HarnessGraphCandidateType.ACTIVATE_NODE,)
    assert successor.candidates[0].node_id == "after"


@pytest.mark.parametrize(
    ("route_id", "terminal_id"),
    (("exit", "exit"), ("exhaustion", "exhausted")),
)
def test_loop_terminal_route_converges_before_common_successor(
    route_id: str,
    terminal_id: str,
) -> None:
    graph = _compile(
        Sequence(
            (
                BoundedLoop(
                    "loop",
                    StepRef("body"),
                    ConditionPredicate(
                        "graph.inputs.continue",
                        "equals",
                        True,
                    ),
                    1,
                    exit=StepRef("exit"),
                    exhaustion=StepRef("exhausted"),
                ),
                StepRef("after"),
            )
        ),
        "body",
        "exit",
        "exhausted",
        "after",
    )
    guard = _node(
        graph,
        "loop",
        "succeeded",
        ordinal=0,
        sequence=1,
        metadata={"selected_loop_route_id": route_id},
    )
    terminal = _node(
        graph,
        terminal_id,
        "succeeded",
        ordinal=1,
        sequence=2,
    )

    join_activation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(guard, terminal)),
    )
    assert _candidate_types(join_activation) == (
        HarnessGraphCandidateType.ACTIVATE_NODE,
    )
    assert join_activation.candidates[0].node_id == "loop:join"
    assert join_activation.candidates[0].payload["selected_route_id"] == route_id

    join = _node(
        graph,
        "loop:join",
        "succeeded",
        ordinal=2,
        sequence=3,
    )
    successor = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(guard, terminal, join)),
    )
    assert _candidate_types(successor) == (HarnessGraphCandidateType.ACTIVATE_NODE,)
    assert successor.candidates[0].node_id == "after"


def test_loop_join_uses_only_final_terminal_route_guard_in_parent_scope() -> None:
    graph = _compile(
        BoundedLoop(
            "loop",
            StepRef("body"),
            ConditionPredicate("graph.inputs.continue", "equals", True),
            2,
            exit=StepRef("exit"),
        ),
        "body",
        "exit",
    )
    continued = _node(
        graph,
        "loop",
        "succeeded",
        ordinal=0,
        sequence=1,
        metadata={"selected_loop_route_id": "continue"},
    )
    exited = _node(
        graph,
        "loop",
        "succeeded",
        ordinal=2,
        sequence=3,
        metadata={"selected_loop_route_id": "exit"},
    )
    exit_node = _node(graph, "exit", "succeeded", ordinal=3, sequence=4)

    evaluation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, nodes=(continued, exited, exit_node)),
    )
    candidates = tuple(
        item
        for item in evaluation.candidates
        if item.candidate_type is HarnessGraphCandidateType.ACTIVATE_NODE
        and item.node_id == "loop:join"
    )

    assert len(candidates) == 1
    assert candidates[0].payload["loop_node_instance_id"] == exited.instance_id


def test_verified_output_requires_explicit_pinned_control_fact_projection() -> None:
    with pytest.raises(HarnessValidationError) as undeclared_payload:
        HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.VERIFIED_OUTPUT,
            "draft",
            "draft-instance",
            1,
            1,
            HarnessContractReference(HarnessContractKind.STEP, "draft", "1"),
            _sha("draft-output"),
            {"recommended_route": "publish"},
        )
    assert undeclared_payload.value.code == "undeclared_graph_control_fact"

    graph = _compile(
        Sequence(
            (
                StepRef("source"),
                Choice(
                    "route",
                    (
                        ChoiceBranch(
                            "publish",
                            StepRef("publish"),
                            0,
                            condition=ConditionPredicate(
                                "node.outputs.classification",
                                "equals",
                                "publish",
                            ),
                        ),
                    ),
                ),
            )
        ),
        "source",
        "publish",
        control_fact_paths_by_step={"source": ("classification",)},
    )
    source_identity = _identity(graph, "source", ordinal=0)
    definition = next(item for item in graph.nodes if item.node_id == "source")
    assert isinstance(definition, HarnessExecutableNode)
    output_payload = {"classification": "publish"}
    output_payload_ref = canonical_checksum(output_payload)
    gate_payload = {
        "passed": True,
        "input_ref": output_payload_ref,
        "result_ref": _sha("source-gate-result"),
        "reason_code": "control_facts_verified",
    }
    activity_evidence = HarnessAttemptEvidenceReference(
        _sha("source-output"),
        HarnessEvidenceKind.ACTIVITY_RESULT,
        source_identity.instance_id,
        1,
        2,
        contract_ref=definition.step_ref,
        payload_ref=output_payload_ref,
    )
    gate_evidence = HarnessAttemptEvidenceReference(
        _sha("source-gate"),
        HarnessEvidenceKind.GATE_RESULT,
        source_identity.instance_id,
        1,
        3,
        contract_ref=definition.gate_refs[0],
        payload_ref=canonical_checksum(gate_payload),
    )
    source = _node(
        graph,
        "source",
        "succeeded",
        ordinal=0,
        sequence=3,
        activation_sequence=1,
        evidence=(activity_evidence, gate_evidence),
    )
    choice = _node(graph, "route", "ready", ordinal=1, sequence=4)
    verified_output = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.VERIFIED_OUTPUT,
        "source",
        source.instance_id,
        1,
        2,
        definition.step_ref,
        activity_evidence.evidence_ref,
        output_payload,
        control_fact_paths=("classification",),
    )
    gate_result = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.GATE_RESULT,
        "source",
        source.instance_id,
        1,
        3,
        definition.gate_refs[0],
        gate_evidence.evidence_ref,
        gate_payload,
    )
    state = _state(graph, nodes=(source, choice))

    selected = HarnessGraphEvaluator().evaluate(
        graph,
        state,
        context=HarnessGraphEvaluationContext(
            observations=(gate_result, verified_output)
        ),
    )
    assert selected.candidates[0].branch_id == "publish"

    renamed_suggestion = replace(
        verified_output,
        payload={"recommended_route": "publish"},
        control_fact_paths=("recommended_route",),
    )
    with pytest.raises(HarnessValidationError) as undeclared_fact:
        HarnessGraphEvaluator().evaluate(
            graph,
            state,
            context=HarnessGraphEvaluationContext(
                observations=(gate_result, renamed_suggestion)
            ),
        )
    assert undeclared_fact.value.code == "unaccepted_graph_observation_rejected"

    replaced_payload = replace(
        verified_output,
        payload={"classification": "hold"},
    )
    with pytest.raises(HarnessValidationError) as evidence_mismatch:
        HarnessGraphEvaluator().evaluate(
            graph,
            state,
            context=HarnessGraphEvaluationContext(
                observations=(gate_result, replaced_payload)
            ),
        )
    assert evidence_mismatch.value.code == "unaccepted_graph_observation_rejected"


def test_evaluator_rejects_mismatched_graph_reference_versions() -> None:
    graph = _compile(StepRef("entry"), "entry")
    state = _state(graph)
    mismatched = replace(
        state,
        graph_ref=HarnessGraphReference(
            "other-graph",
            replace(graph.workflow_ref, version="other-version"),
            graph.schema_version,
            graph.compiler_version,
            graph.condition_policy_version,
            graph.checksum,
        ),
        projection_checksum=None,
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphEvaluator().evaluate(graph, mismatched)
    assert captured.value.code == "graph_evaluator_graph_mismatch"


def test_activation_budget_exhaustion_blocks_new_work() -> None:
    graph = _compile(StepRef("entry"), "entry")
    budgets = HarnessGraphBudgetState(
        (
            HarnessBudgetCounterState("node_activations", 1, used=1),
            HarnessBudgetCounterState("max_parallelism", 1),
            HarnessBudgetCounterState("max_active_nodes", 1),
        )
    )

    evaluation = HarnessGraphEvaluator().evaluate(
        graph,
        _state(graph, budgets=budgets),
    )

    assert _candidate_types(evaluation) == (HarnessGraphCandidateType.HALT_RUN,)
    assert evaluation.candidates[0].reason_code == "node_activation_budget_exhausted"


def _candidate_types(evaluation) -> tuple[HarnessGraphCandidateType, ...]:
    return tuple(item.candidate_type for item in evaluation.candidates)


def _compensation_state() -> tuple[
    NormalizedHarnessGraph,
    HarnessGraphState,
    HarnessCompensationEntry,
    HarnessCompensationEntry,
]:
    graph = _compile(
        Sequence((StepRef("prepare"), StepRef("publish"), StepRef("forward"))),
        "prepare",
        "publish",
        "forward",
        "undo-prepare",
        "undo-publish",
        compensations=(
            CompensationBinding(
                "undo-prepare",
                "prepare",
                "undo-prepare",
                "publication.undo-prepare@1",
                "publication.undo-prepare.activity@1",
            ),
            CompensationBinding(
                "undo-publish",
                "publish",
                "undo-publish",
                "publication.undo-publish@1",
                "publication.undo-publish.activity@1",
            ),
        ),
    )
    prepare_identity = _identity(graph, "prepare", ordinal=0)
    publish_identity = _identity(graph, "publish", ordinal=1)
    prepare_effect = _sha("prepare-effect")
    publish_effect = _sha("publish-effect")
    prepare = _node(
        graph,
        "prepare",
        "succeeded",
        ordinal=0,
        sequence=3,
        evidence=(
            HarnessAttemptEvidenceReference(
                prepare_effect,
                HarnessEvidenceKind.SIDE_EFFECT_OUTCOME,
                prepare_identity.instance_id,
                1,
                3,
            ),
        ),
    )
    publish = _node(
        graph,
        "publish",
        "succeeded",
        ordinal=1,
        sequence=5,
        evidence=(
            HarnessAttemptEvidenceReference(
                publish_effect,
                HarnessEvidenceKind.SIDE_EFFECT_OUTCOME,
                publish_identity.instance_id,
                1,
                5,
            ),
        ),
    )
    earlier = HarnessCompensationEntry(
        "entry-prepare",
        prepare.instance_id,
        prepare_effect,
        3,
        HarnessContractReference(
            "compensation",
            "publication.undo-prepare",
            "1",
        ),
        HarnessContractReference(
            "activity",
            "publication.undo-prepare.activity",
            "1",
        ),
        "undo:run-1:prepare",
        1,
        last_event_sequence=3,
    )
    later = HarnessCompensationEntry(
        "entry-publish",
        publish.instance_id,
        publish_effect,
        5,
        HarnessContractReference(
            "compensation",
            "publication.undo-publish",
            "1",
        ),
        HarnessContractReference(
            "activity",
            "publication.undo-publish.activity",
            "1",
        ),
        "undo:run-1:publish",
        1,
        last_event_sequence=5,
    )
    return (
        graph,
        _state(
            graph,
            nodes=(prepare, publish),
            compensations=(earlier, later),
            metadata={"execution_mode": "compensating"},
        ),
        earlier,
        later,
    )


def _compile(
    root,
    *step_ids: str,
    compensations: tuple[CompensationBinding, ...] = (),
    control_fact_paths_by_step: Mapping[str, tuple[str, ...]] | None = None,
) -> NormalizedHarnessGraph:
    declared_step_ids = step_ids or ("anchor",)
    control_facts = control_fact_paths_by_step or {}
    workflow = HarnessWorkflowSpec(
        workflow_id="evaluation",
        workflow_version="2",
        steps=tuple(
            HarnessStepSpec(
                step_id=step_id,
                worker_type="llm",
                quality_gate=(
                    f"{step_id}.control-gate@1" if step_id in control_facts else None
                ),
                metadata={
                    "step_version": "1",
                    "worker_version": "1",
                    "activity_contract_ref": f"{step_id}.activity@1",
                    **(
                        {"control_fact_paths": control_facts[step_id]}
                        if step_id in control_facts
                        else {}
                    ),
                },
            )
            for step_id in declared_step_ids
        ),
        entry_step_id=declared_step_ids[0],
        graph=HarnessGraphSpec(
            "evaluation-graph",
            root,
            compensations=compensations,
        ),
    )
    return HarnessWorkflowGraphCompiler().compile(workflow).graph


def _state(
    graph: NormalizedHarnessGraph,
    *,
    nodes: tuple[HarnessNodeInstanceState, ...] = (),
    joins: tuple[HarnessJoinState, ...] = (),
    loops: tuple[HarnessLoopCounterState, ...] = (),
    waits: tuple[HarnessWaitRegistration, ...] = (),
    compensations: tuple[HarnessCompensationEntry, ...] = (),
    metadata: Mapping[str, object] | None = None,
    budgets: HarnessGraphBudgetState | None = None,
) -> HarnessGraphState:
    last_sequence = max(
        (
            0,
            *(item.last_event_sequence for item in nodes),
            *(item.last_event_sequence for item in joins),
            *(item.last_event_sequence for item in loops),
            *(item.last_event_sequence for item in waits),
            *(item.last_event_sequence for item in compensations),
        )
    )
    return HarnessGraphState(
        run_id="run-1",
        graph_ref=HarnessGraphReference(
            graph.graph_id,
            graph.workflow_ref,
            graph.schema_version,
            graph.compiler_version,
            graph.condition_policy_version,
            graph.checksum,
        ),
        lifecycle="running",
        node_instances=nodes,
        join_states=joins,
        loop_counters=loops,
        wait_registrations=waits,
        compensation_stack=compensations,
        budgets=(
            HarnessGraphBudgetState(
                (
                    HarnessBudgetCounterState("node_activations", 1_000),
                    HarnessBudgetCounterState("compensations", 1_000),
                    HarnessBudgetCounterState("max_parallelism", 8),
                    HarnessBudgetCounterState("max_active_nodes", 16),
                )
            )
            if budgets is None
            else budgets
        ),
        last_event_sequence=last_sequence,
        metadata={} if metadata is None else metadata,
    )


def _identity(
    graph: NormalizedHarnessGraph,
    node_id: str,
    *,
    ordinal: int,
    branch_path: tuple[str, ...] = (),
    iteration_vector: tuple[HarnessLoopIteration, ...] = (),
) -> HarnessNodeInstanceIdentity:
    return HarnessNodeInstanceIdentity(
        "run-1",
        graph.checksum,
        node_id,
        branch_path=branch_path,
        iteration_vector=iteration_vector,
        activation_ordinal=ordinal,
    )


def _node(
    graph: NormalizedHarnessGraph,
    node_id: str,
    status: str,
    *,
    ordinal: int,
    sequence: int,
    activation_sequence: int | None = None,
    branch_path: tuple[str, ...] = (),
    iteration_vector: tuple[HarnessLoopIteration, ...] = (),
    evidence: tuple[HarnessAttemptEvidenceReference, ...] = (),
    metadata: Mapping[str, object] | None = None,
) -> HarnessNodeInstanceState:
    definition = next(item for item in graph.nodes if item.node_id == node_id)
    identity = _identity(
        graph,
        node_id,
        ordinal=ordinal,
        branch_path=branch_path,
        iteration_vector=iteration_vector,
    )
    if isinstance(definition, HarnessExecutableNode):
        attempt = 0 if status in {"pending", "ready"} else 1
        step_status = {
            "pending": "pending",
            "ready": "pending",
            "running": "running",
            "waiting": "waiting_approval",
            "succeeded": "succeeded",
            "failed": "failed",
            "halted": "halted",
            "cancelled": "skipped",
            "skipped": "skipped",
            "compensating": "running",
            "compensated": "succeeded",
        }[status]
        return HarnessNodeInstanceState(
            identity,
            definition.node_kind,
            status,
            step_id=definition.step_id,
            step_ref=definition.step_ref,
            step_status=step_status,
            attempt=attempt,
            evidence_refs=evidence,
            activation_sequence=(
                sequence if activation_sequence is None else activation_sequence
            ),
            last_event_sequence=sequence,
            metadata={} if metadata is None else metadata,
        )
    return HarnessNodeInstanceState(
        identity,
        definition.node_kind,
        status,
        activation_sequence=(
            sequence if activation_sequence is None else activation_sequence
        ),
        last_event_sequence=sequence,
        metadata={} if metadata is None else metadata,
    )


def _wait_registration(
    node_instance_id: str,
    status: str,
    *,
    sequence: int,
) -> HarnessWaitRegistration:
    return HarnessWaitRegistration(
        "approval-wait",
        node_instance_id,
        "approval",
        _sha("correlation"),
        _sha("tenant"),
        _sha("identity"),
        "editor.approval@1",
        sequence,
        status=status,
        resolution_event_ref=(
            None if status == "registered" else _sha("wait-resolution")
        ),
        last_event_sequence=sequence,
    )


def _sha(value: str) -> str:
    return canonical_checksum({"value": value})
