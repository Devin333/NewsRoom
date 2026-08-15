from __future__ import annotations

import ast
import builtins
import random
import socket
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import framework.harness.control_plane.graph_evaluator as graph_evaluator_module
import framework.harness.control_plane.scheduler as scheduler_module
import framework.harness.control_plane.step_lifecycle as step_lifecycle_module
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_evaluator import (
    GraphEvaluation,
    HarnessAcceptedGraphObservation,
    HarnessGraphCandidate,
    HarnessGraphCandidateType,
    HarnessGraphEvaluationContext,
    HarnessGraphObservationType,
    WorkflowGraphEvaluator,
)
from framework.harness.control_plane.graph_state import (
    HarnessActiveActivityState,
    HarnessAttemptEvidenceReference,
    HarnessBudgetCounterState,
    HarnessCompensationEntry,
    HarnessEvidenceKind,
    HarnessGraphBudgetState,
    HarnessGraphReference,
    HarnessGraphState,
    HarnessNodeInstanceIdentity,
    HarnessNodeInstanceState,
)
from framework.harness.control_plane.scheduler import (
    HarnessGraphStepSchedulingInput,
    HarnessScheduler,
)
from framework.harness.control_plane.step_lifecycle import (
    StepLifecycleBudget,
    StepLifecycleObservations,
    StepWorkerObservation,
)
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.dsl import (
    Choice,
    ChoiceBranch,
    CompensationBinding,
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    StepRef,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec


class _CandidateEvaluator(WorkflowGraphEvaluator):
    __slots__ = (
        "_candidates",
        "_context_checksum",
        "_graph_checksum",
        "_state_checksum",
    )

    def __init__(
        self,
        candidates: tuple[HarnessGraphCandidate, ...],
        *,
        graph_checksum: str | None = None,
        state_checksum: str | None = None,
        context_checksum: str | None = None,
    ) -> None:
        self._candidates = candidates
        self._graph_checksum = graph_checksum
        self._state_checksum = state_checksum
        self._context_checksum = context_checksum

    def evaluate(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        *,
        context: HarnessGraphEvaluationContext | None = None,
    ) -> GraphEvaluation:
        accepted_context = context or HarnessGraphEvaluationContext()
        return GraphEvaluation(
            graph_checksum=self._graph_checksum or graph.checksum,
            state_checksum=self._state_checksum or state.projection_checksum,
            context_checksum=self._context_checksum or accepted_context.checksum,
            candidates=self._candidates,
            ready_node_instance_ids=state.ready_node_ids,
            running_node_instance_ids=state.running_node_ids,
            waiting_node_instance_ids=state.waiting_node_ids,
            terminal_node_instance_ids=state.terminal_node_ids,
            blocked_node_ids=(),
        )


def test_scheduler_facade_activates_entry_with_one_canonical_decision() -> None:
    workflow, graph = _linear_workflow("entry")
    state = _state(graph)

    decision = HarnessScheduler().next_decision(state, graph=graph)

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
    assert decision.node_id == "entry"
    assert decision.node_instance_id is None
    assert decision.graph_ref == state.graph_ref
    assert decision.input_projection_checksum == state.projection_checksum
    assert decision.observation_checksum.startswith("sha256:")
    assert decision.decision_checksum.startswith("sha256:")
    assert decision.scheduler_version == "newsroom.harness-graph-control-policy/v1"
    assert decision.evaluator_version == "newsroom.harness-graph-evaluator/v1"
    assert decision.step_lifecycle_version == "newsroom.harness-step-lifecycle/v1"
    assert (
        decision.binding_versions["step"]
        == _definition(
            graph,
            "entry",
        ).step_ref.exact_ref
    )
    assert workflow.steps[0].step_id == "entry"


def test_real_choice_evaluation_maps_to_typed_scheduler_decision() -> None:
    _, graph = _choice_workflow()
    route = _control_node(graph, "route", ordinal=1)

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(route,)),
        graph=graph,
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE
    assert decision.node_instance_id == route.instance_id
    assert decision.target_node_ids == ("publish",)


def test_terminal_graph_state_is_quiescent() -> None:
    _, graph = _linear_workflow("entry")
    terminal = _executable_node(
        graph,
        "entry",
        status="succeeded",
        step_status="succeeded",
        ordinal=1,
        attempt=1,
        last_sequence=2,
    )
    state = _state(
        graph,
        nodes=(terminal,),
        lifecycle="completed",
        outcome="succeeded",
    )

    decision = HarnessScheduler().next_decision(state, graph=graph)

    assert decision is None


def test_real_evaluator_terminal_evidence_is_accepted() -> None:
    _, graph = _linear_workflow("entry")
    terminal = _executable_node(
        graph,
        "entry",
        status="succeeded",
        step_status="succeeded",
        ordinal=1,
        attempt=1,
        last_sequence=2,
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(terminal,)),
        graph=graph,
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.COMPLETE_RUN
    assert decision.evidence_refs == (canonical_checksum(terminal.to_dict()),)


@pytest.mark.parametrize(
    ("status", "step_status", "attempt", "expected_type"),
    (
        ("pending", "pending", 0, None),
        (
            "waiting",
            "waiting_approval",
            0,
            HarnessGraphDecisionType.PROJECT_RUN_WAITING,
        ),
        ("cancel_requested", "running", 1, None),
    ),
)
def test_non_step_runnable_executable_is_quiescent_without_input(
    status: str,
    step_status: str,
    attempt: int,
    expected_type: HarnessGraphDecisionType | None,
) -> None:
    _, graph = _linear_workflow("entry")
    node = _executable_node(
        graph,
        "entry",
        status=status,
        step_status=step_status,
        ordinal=1,
        attempt=attempt,
    )
    activities = (
        (_active_activity(graph, node),) if status == "cancel_requested" else ()
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,), active_activities=activities),
        graph=graph,
    )

    if expected_type is None:
        assert decision is None
    else:
        assert decision is not None
        assert decision.decision_type is expected_type


def test_scheduler_rejects_stale_evaluator_checksums() -> None:
    _, graph = _linear_workflow("entry")
    state = _state(graph)
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.ACTIVATE_NODE,
                    "entry_ready",
                    40,
                    node_id="entry",
                ),
            ),
            state_checksum=canonical_checksum({"state": "stale"}),
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        scheduler.next_decision(state, graph=graph)

    assert captured.value.code == "graph_scheduler_evaluation_mismatch"


def test_scheduler_rejects_candidate_evidence_outside_accepted_input() -> None:
    _, graph = _linear_workflow("entry")
    state = _state(graph)
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.ACTIVATE_NODE,
                    "entry_ready",
                    40,
                    node_id="entry",
                    evidence_refs=(canonical_checksum({"forged": "evidence"}),),
                ),
            )
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        scheduler.next_decision(state, graph=graph)

    assert captured.value.code == "graph_scheduler_candidate_evidence_mismatch"


def test_scheduler_rejects_unknown_candidate_identity() -> None:
    _, graph = _linear_workflow("entry")
    state = _state(graph)
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.ACTIVATE_NODE,
                    "unknown_ready",
                    40,
                    node_id="unknown",
                ),
            )
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        scheduler.next_decision(state, graph=graph)

    assert captured.value.code == "graph_scheduler_candidate_identity_mismatch"


def test_scheduler_rejects_unknown_state_node_before_evaluation() -> None:
    _, graph = _linear_workflow("entry")
    ghost = HarnessNodeInstanceState(
        HarnessNodeInstanceIdentity(
            "run-scheduler",
            graph.checksum,
            "ghost",
            activation_ordinal=1,
        ),
        "terminal",
        "ready",
        activation_sequence=1,
        last_event_sequence=1,
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessScheduler().next_decision(
            _state(graph, nodes=(ghost,)),
            graph=graph,
        )

    assert captured.value.code == "graph_scheduler_state_identity_mismatch"


def test_scheduler_rejects_candidate_type_for_wrong_node_kind() -> None:
    workflow, graph = _linear_workflow("entry")
    entry = _executable_node(graph, "entry", ordinal=1)
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.SELECT_CHOICE,
                    "invalid_choice",
                    20,
                    node_id="entry",
                    node_instance_id=entry.instance_id,
                ),
            )
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        scheduler.next_decision(
            _state(graph, nodes=(entry,)),
            graph=graph,
            step_inputs=(_step_input(workflow, entry),),
        )

    assert captured.value.code == "graph_scheduler_candidate_kind_mismatch"


def test_qualified_step_reference_supports_colons_inside_step_id() -> None:
    workflow, graph = _linear_workflow("phase:analyze")
    node = _executable_node(graph, "phase:analyze", ordinal=1)

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
        step_inputs=(_step_input(workflow, node),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE
    assert decision.step_ref.contract_id == "scheduler:phase:analyze"


def test_committed_step_outcome_reconciliation_precedes_graph_safety() -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status="running",
        step_status="running",
        ordinal=1,
        attempt=1,
        last_sequence=2,
        with_activity_evidence=True,
    )
    state = _state(graph, nodes=(node,))
    step_input = _succeeded_worker_input(workflow, graph, node)
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.HALT_RUN,
                    "node_activation_budget_exhausted",
                    0,
                ),
            )
        )
    )

    decision = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(step_input,),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT
    assert decision.reason_code == "worker_succeeded_verify"
    assert decision.evidence_refs == (node.evidence_refs[0].evidence_ref,)


def test_graph_safety_precedes_uncommitted_step_lifecycle() -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(graph, "analyze", ordinal=1)
    state = _state(graph, nodes=(node,))
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.ACTIVATE_NODE,
                    "another_node_ready",
                    40,
                    node_id="analyze",
                ),
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.HALT_RUN,
                    "graph_budget_exhausted",
                    0,
                ),
            )
        )
    )

    decision = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(_step_input(workflow, node),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.HALT_RUN
    assert decision.reason_code == "graph_budget_exhausted"


def test_cancel_requested_node_never_redispatches_without_reconciliation() -> None:
    _, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status="cancel_requested",
        step_status="running",
        ordinal=1,
        attempt=1,
        last_sequence=2,
    )
    state = _state(
        graph,
        nodes=(node,),
        active_activities=(_active_activity(graph, node),),
    )

    decision = HarnessScheduler().next_decision(
        state,
        graph=graph,
    )

    assert decision is None


@pytest.mark.parametrize(
    ("status", "step_status", "attempt"),
    (
        ("pending", "pending", 0),
        ("waiting", "waiting_approval", 0),
        ("cancel_requested", "running", 1),
    ),
)
def test_non_step_runnable_executable_rejects_step_input(
    status: str,
    step_status: str,
    attempt: int,
) -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status=status,
        step_status=step_status,
        ordinal=1,
        attempt=attempt,
    )
    activities = (
        (_active_activity(graph, node),) if status == "cancel_requested" else ()
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessScheduler().next_decision(
            _state(graph, nodes=(node,), active_activities=activities),
            graph=graph,
            step_inputs=(_step_input(workflow, node),),
        )

    assert captured.value.code == "unexpected_graph_step_scheduling_input"


@pytest.mark.parametrize(
    ("status", "step_status"),
    (
        ("ready", "pending"),
        ("running", "planning"),
    ),
)
def test_step_runnable_executable_requires_step_input(
    status: str,
    step_status: str,
) -> None:
    _, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status=status,
        step_status=step_status,
        ordinal=1,
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.HALT_RUN
    assert decision.reason_code == "step_lifecycle_input_missing"


@pytest.mark.parametrize(
    ("step_status", "attempt", "with_activity_evidence", "expected_type"),
    (
        ("pending", 0, False, HarnessGraphDecisionType.ENTER_STEP_PHASE),
        ("plan_verified", 0, False, HarnessGraphDecisionType.DISPATCH_ACTIVITY),
        ("running", 1, True, HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT),
    ),
)
def test_compensating_executable_retains_exact_bindings_through_step_lifecycle(
    step_status: str,
    attempt: int,
    with_activity_evidence: bool,
    expected_type: HarnessGraphDecisionType,
) -> None:
    workflow, graph = _compensation_workflow()
    origin, node, entry = _running_compensation_projection(
        graph,
        step_status=step_status,
        attempt=attempt,
        with_activity_evidence=with_activity_evidence,
    )
    state = _state(
        graph,
        nodes=(origin, node),
        compensations=(entry,),
        metadata={"execution_mode": "compensating"},
    )
    step_input = (
        _succeeded_worker_input(workflow, graph, node)
        if with_activity_evidence
        else _step_input(workflow, node)
    )

    decision = HarnessScheduler().next_decision(
        state,
        graph=graph,
        step_inputs=(step_input,),
    )

    assert decision is not None
    assert decision.decision_type is expected_type
    definition = _definition(graph, "compensation:undo-publish")
    assert dict(decision.binding_versions) == {
        "step": definition.step_ref.exact_ref,
        "worker": definition.worker_ref.exact_ref,
        "activity": entry.activity_ref.exact_ref,
        "gate:0000": definition.gate_refs[0].exact_ref,
        "compensation": entry.handler_ref.exact_ref,
    }
    assert entry.activity_ref != definition.activity_ref


def test_waiting_executable_does_not_block_later_ready_node() -> None:
    workflow, graph = _linear_workflow("waiting", "ready")
    waiting = _executable_node(
        graph,
        "waiting",
        status="waiting",
        step_status="waiting_approval",
        ordinal=1,
    )
    ready = _executable_node(graph, "ready", ordinal=2)

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(waiting, ready)),
        graph=graph,
        step_inputs=(_step_input(workflow, ready),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE
    assert decision.node_instance_id == ready.instance_id


def test_approved_waiting_executable_resumes_verify_with_current_attempt_evidence() -> (
    None
):
    workflow, graph = _linear_workflow("approval")
    node = _executable_node(
        graph,
        "approval",
        status="waiting",
        step_status="waiting_approval",
        ordinal=1,
        last_sequence=2,
        metadata={"approval_granted": True},
    )
    definition = _definition(graph, "approval")
    approval = HarnessAttemptEvidenceReference(
        canonical_checksum({"approval": node.instance_id}),
        HarnessEvidenceKind.APPROVAL,
        node.instance_id,
        node.attempt,
        node.last_event_sequence,
        contract_ref=definition.step_ref,
        payload_ref=canonical_checksum({"approved": True}),
    )
    node = HarnessNodeInstanceState(
        node.identity,
        node.node_kind,
        node.status,
        step_id=node.step_id,
        step_ref=node.step_ref,
        step_status=node.step_status,
        attempt=node.attempt,
        evidence_refs=(approval,),
        activation_sequence=node.activation_sequence,
        last_event_sequence=node.last_event_sequence,
        metadata=node.metadata,
    )
    step = next(item for item in workflow.steps if item.step_id == node.step_id)
    step_input = HarnessGraphStepSchedulingInput(
        node.instance_id,
        step,
        StepLifecycleObservations.for_node(
            node,
            approval_granted=True,
            approval_evidence=approval,
        ),
        _budget(),
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
        step_inputs=(step_input,),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT
    assert decision.reason_code == "approval_granted_verify"
    assert decision.evidence_refs == (approval.evidence_ref,)


def test_first_activity_dispatch_allocates_attempt_one() -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status="running",
        step_status="plan_verified",
        ordinal=1,
        attempt=0,
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
        step_inputs=(_step_input(workflow, node),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
    assert decision.attempt == 1
    assert decision.payload["source_attempt"] == 0
    assert decision.payload["activity_attempt"] == 1


def test_activity_dispatch_waits_for_a_physical_slot_and_resumes_stably() -> None:
    workflow, graph = _linear_workflow("first", "second")
    first = _executable_node(
        graph,
        "first",
        status="running",
        step_status="running",
        ordinal=1,
        attempt=1,
        last_sequence=2,
    )
    second = _executable_node(
        graph,
        "second",
        status="running",
        step_status="plan_verified",
        ordinal=2,
        last_sequence=2,
    )
    first_definition = _definition(graph, "first")
    activity = HarnessActiveActivityState(
        "activity-first",
        first_definition.activity_ref,
        first.instance_id,
        1,
        "activity-first:attempt:1",
        1,
        2,
    )
    saturated = _state(
        graph,
        nodes=(first, second),
        active_activities=(activity,),
        max_parallelism=1,
    )

    deferred = HarnessScheduler().next_decision(
        saturated,
        graph=graph,
        step_inputs=(
            _step_input(workflow, first),
            _step_input(workflow, second),
        ),
    )

    assert deferred is None

    completed_first = HarnessNodeInstanceState(
        first.identity,
        first.node_kind,
        "succeeded",
        step_id=first.step_id,
        step_ref=first.step_ref,
        step_status="succeeded",
        attempt=first.attempt,
        activation_sequence=first.activation_sequence,
        last_event_sequence=3,
    )
    released = _state(
        graph,
        nodes=(completed_first, second),
        max_parallelism=1,
    )

    admitted = HarnessScheduler().next_decision(
        released,
        graph=graph,
        step_inputs=(_step_input(workflow, second),),
    )

    assert admitted is not None
    assert admitted.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
    assert admitted.node_instance_id == second.instance_id


def test_retry_activity_dispatch_allocates_next_attempt() -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status="running",
        step_status="retrying",
        ordinal=1,
        attempt=1,
        last_sequence=2,
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
        step_inputs=(_step_input(workflow, node),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
    assert decision.attempt == 2
    assert decision.payload["source_attempt"] == 1
    assert decision.payload["activity_attempt"] == 2


def test_recovery_redispatch_reuses_running_attempt_identity() -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status="running",
        step_status="running",
        ordinal=1,
        attempt=1,
        last_sequence=2,
    )

    decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
        step_inputs=(_step_input(workflow, node),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
    assert decision.attempt == 1
    assert decision.payload["source_attempt"] == 1
    assert decision.payload["activity_attempt"] == 1


def test_equal_timestamps_still_use_activation_order_not_event_recency() -> None:
    workflow, graph = _linear_workflow("first", "second")
    accepted_at = "2026-07-30T09:00:00Z"
    later = _executable_node(
        graph,
        "second",
        ordinal=20,
        last_sequence=2,
        metadata={"accepted_at": accepted_at},
    )
    earlier = _executable_node(
        graph,
        "first",
        ordinal=10,
        last_sequence=100,
        metadata={"accepted_at": accepted_at},
    )
    state = _state(graph, nodes=(later, earlier))
    earlier_input = _step_input(workflow, earlier)
    later_input = _step_input(workflow, later)
    scheduler = HarnessScheduler()

    forward = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(earlier_input, later_input),
    )
    reverse = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(later_input, earlier_input),
    )

    assert forward is not None
    assert reverse is not None
    assert forward.node_instance_id == earlier.instance_id
    assert forward.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE
    assert reverse.to_dict() == forward.to_dict()


def test_graph_control_precedes_activation_waiting_and_completion() -> None:
    workflow, graph = _choice_workflow()
    route = _control_node(graph, "route", ordinal=1)
    state = _state(graph, nodes=(route,))
    candidates = (
        HarnessGraphCandidate(
            HarnessGraphCandidateType.COMPLETE_RUN,
            "complete",
            60,
        ),
        HarnessGraphCandidate(
            HarnessGraphCandidateType.PROJECT_RUN_WAITING,
            "waiting",
            60,
        ),
        HarnessGraphCandidate(
            HarnessGraphCandidateType.ACTIVATE_NODE,
            "activation",
            40,
            node_id="publish",
        ),
        HarnessGraphCandidate(
            HarnessGraphCandidateType.SELECT_CHOICE,
            "choice_selected",
            20,
            node_id="route",
            node_instance_id=route.instance_id,
            target_node_ids=("publish",),
            branch_id="publish-branch",
        ),
    )

    decision = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(tuple(reversed(candidates)))
    ).next_decision(state, graph=graph)

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE
    assert decision.target_node_ids == ("publish",)
    assert decision.payload["graph_candidate"]["branch_id"] == "publish-branch"
    assert workflow.workflow_id == "choice-scheduler"


def test_active_step_precedes_join_graph_control() -> None:
    workflow, graph = _parallel_workflow()
    active = _executable_node(graph, "first", ordinal=1)
    join_definition = next(
        item for item in graph.nodes if item.node_kind.value == "join_all"
    )
    join = _control_node(graph, join_definition.node_id, ordinal=2)
    scheduler = HarnessScheduler(
        graph_evaluator=_CandidateEvaluator(
            (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.SATISFY_JOIN,
                    "parallel_all_join_satisfied",
                    10,
                    node_id=join_definition.node_id,
                    node_instance_id=join.instance_id,
                ),
            )
        )
    )

    decision = scheduler.next_decision(
        _state(graph, nodes=(active, join)),
        graph=graph,
        step_inputs=(_step_input(workflow, active),),
    )

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE
    assert decision.node_instance_id == active.instance_id


def test_repeated_evaluation_and_candidate_permutation_keep_identity() -> None:
    _, graph = _linear_workflow("first", "second")
    state = _state(graph)
    first = HarnessGraphCandidate(
        HarnessGraphCandidateType.ACTIVATE_NODE,
        "ready",
        40,
        node_id="first",
    )
    second = HarnessGraphCandidate(
        HarnessGraphCandidateType.ACTIVATE_NODE,
        "ready",
        40,
        node_id="second",
    )
    scheduler_a = HarnessScheduler(graph_evaluator=_CandidateEvaluator((second, first)))
    scheduler_b = HarnessScheduler(graph_evaluator=_CandidateEvaluator((first, second)))

    expected = scheduler_a.next_decision(state, graph=graph)
    permuted = scheduler_b.next_decision(state, graph=graph)

    assert expected is not None
    assert permuted is not None
    assert expected.node_id == "first"
    assert permuted.to_dict() == expected.to_dict()
    for _ in range(20):
        repeated = scheduler_a.next_decision(state, graph=graph)
        assert repeated is not None
        assert repeated.to_dict() == expected.to_dict()


def test_unordered_graph_observations_keep_scheduler_checksum() -> None:
    _, graph = _linear_workflow("entry")
    state = _state(graph)
    first = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.WORKER_STATUS,
        "entry",
        "instance-a",
        1,
        2,
        HarnessContractReference(HarnessContractKind.WORKER, "entry", "1"),
        canonical_checksum({"evidence": "a"}),
        payload={"status": "succeeded"},
    )
    second = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.WORKER_STATUS,
        "entry",
        "instance-b",
        1,
        1,
        HarnessContractReference(HarnessContractKind.WORKER, "entry", "1"),
        canonical_checksum({"evidence": "b"}),
        payload={"status": "failed"},
    )
    candidate = HarnessGraphCandidate(
        HarnessGraphCandidateType.ACTIVATE_NODE,
        "entry_ready",
        40,
        node_id="entry",
    )
    scheduler = HarnessScheduler(graph_evaluator=_CandidateEvaluator((candidate,)))

    forward = scheduler.next_decision(
        state,
        graph=graph,
        graph_context=HarnessGraphEvaluationContext(observations=(first, second)),
    )
    reverse = scheduler.next_decision(
        state,
        graph=graph,
        graph_context=HarnessGraphEvaluationContext(observations=(second, first)),
    )

    assert forward is not None
    assert reverse is not None
    assert forward.observation_checksum == reverse.observation_checksum
    assert forward.to_dict() == reverse.to_dict()


def test_every_graph_candidate_type_has_a_typed_decision_mapping() -> None:
    decision_values = {item.value for item in HarnessGraphDecisionType}

    assert {item.value for item in HarnessGraphCandidateType}.issubset(decision_values)


@pytest.mark.parametrize(
    "suggestions",
    (
        {"route": "publish"},
        {"winner": "worker-selected"},
        {"continue_loop": True},
        {"quality_verdict": {"passed": True}},
        {"compensate": False},
        {"approval_granted": True},
        {"memory_write": {"namespace": "active"}},
        {"publication": {"approved": True}},
    ),
)
def test_worker_control_suggestions_do_not_change_decision_identity(
    suggestions: Mapping[str, Any],
) -> None:
    workflow, graph = _linear_workflow("analyze")
    node = _executable_node(
        graph,
        "analyze",
        status="running",
        step_status="running",
        ordinal=1,
        attempt=1,
        last_sequence=2,
        with_activity_evidence=True,
    )
    state = _state(graph, nodes=(node,))
    baseline = _succeeded_worker_input(workflow, graph, node)
    suggested = _succeeded_worker_input(
        workflow,
        graph,
        node,
        suggestions=suggestions,
    )
    scheduler = HarnessScheduler()

    baseline_decision = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(baseline,),
    )
    suggested_decision = scheduler.next_decision(
        state,
        graph=graph,
        step_inputs=(suggested,),
    )

    assert baseline.control_checksum == suggested.control_checksum
    assert baseline_decision is not None
    assert suggested_decision is not None
    assert baseline_decision.to_dict() == suggested_decision.to_dict()


def test_scheduler_components_do_not_read_external_runtime_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden_imports = {
        "http",
        "os",
        "random",
        "requests",
        "secrets",
        "socket",
        "subprocess",
        "time",
        "urllib",
        "uuid",
    }
    for module in (
        scheduler_module,
        graph_evaluator_module,
        step_lifecycle_module,
    ):
        source_path = Path(module.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert imported_roots.isdisjoint(forbidden_imports)
        mutable_constants = {
            name
            for name, value in vars(module).items()
            if name.isupper() and isinstance(value, dict | list | set)
        }
        assert not mutable_constants

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("scheduler touched an external runtime source")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(random, "choice", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(uuid, "uuid4", forbidden)

    _, graph = _linear_workflow("entry")
    state = _state(graph)
    decision = HarnessScheduler().next_decision(state, graph=graph)

    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE

    workflow, graph = _linear_workflow("step")
    node = _executable_node(graph, "step", ordinal=1)
    step_decision = HarnessScheduler().next_decision(
        _state(graph, nodes=(node,)),
        graph=graph,
        step_inputs=(_step_input(workflow, node),),
    )

    assert step_decision is not None
    assert step_decision.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE


def _linear_workflow(
    *step_ids: str,
) -> tuple[HarnessWorkflowSpec, NormalizedHarnessGraph]:
    workflow = HarnessWorkflowSpec(
        workflow_id="scheduler",
        workflow_version="2",
        steps=tuple(
            HarnessStepSpec(
                step_id,
                "llm",
                metadata={"step_version": "1", "worker_version": "1"},
            )
            for step_id in step_ids
        ),
        entry_step_id=step_ids[0],
    )
    return workflow, HarnessWorkflowGraphCompiler().compile(workflow).graph


def _compensation_workflow() -> tuple[HarnessWorkflowSpec, NormalizedHarnessGraph]:
    workflow = HarnessWorkflowSpec(
        workflow_id="compensation-scheduler",
        workflow_version="2",
        steps=(
            HarnessStepSpec(
                "publish",
                "llm",
                side_effect_handler="publication.effect@1",
                metadata={"step_version": "1", "worker_version": "1"},
            ),
            HarnessStepSpec(
                "undo",
                "llm",
                quality_gate="compensation.schema@3",
                metadata={"step_version": "4", "worker_version": "5"},
            ),
        ),
        entry_step_id="publish",
        graph=HarnessGraphSpec(
            "compensation-scheduler-graph",
            StepRef("publish"),
            compensations=(
                CompensationBinding(
                    "undo-publish",
                    "publish",
                    "undo",
                    "publication.undo@6",
                    "publication.undo.activity@7",
                ),
            ),
        ),
    )
    return workflow, HarnessWorkflowGraphCompiler().compile(workflow).graph


def _choice_workflow() -> tuple[HarnessWorkflowSpec, NormalizedHarnessGraph]:
    workflow = HarnessWorkflowSpec(
        workflow_id="choice-scheduler",
        workflow_version="2",
        steps=(
            HarnessStepSpec(
                "publish",
                "llm",
                metadata={"step_version": "1", "worker_version": "1"},
            ),
        ),
        entry_step_id="publish",
        graph=HarnessGraphSpec(
            "choice-scheduler-graph",
            Choice(
                "route",
                (
                    ChoiceBranch(
                        "publish-branch",
                        StepRef("publish"),
                        0,
                        is_default=True,
                    ),
                ),
            ),
        ),
    )
    return workflow, HarnessWorkflowGraphCompiler().compile(workflow).graph


def _parallel_workflow() -> tuple[HarnessWorkflowSpec, NormalizedHarnessGraph]:
    workflow = HarnessWorkflowSpec(
        workflow_id="parallel-scheduler",
        workflow_version="2",
        steps=(
            HarnessStepSpec(
                "first",
                "llm",
                metadata={"step_version": "1", "worker_version": "1"},
            ),
            HarnessStepSpec(
                "second",
                "llm",
                metadata={"step_version": "1", "worker_version": "1"},
            ),
        ),
        entry_step_id="first",
        graph=HarnessGraphSpec(
            "parallel-scheduler-graph",
            ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("first-branch", StepRef("first"), "first"),
                    ParallelBranch(
                        "second-branch",
                        StepRef("second"),
                        "second",
                    ),
                ),
            ),
        ),
    )
    return workflow, HarnessWorkflowGraphCompiler().compile(workflow).graph


def _state(
    graph: NormalizedHarnessGraph,
    *,
    nodes: tuple[HarnessNodeInstanceState, ...] = (),
    active_activities: tuple[HarnessActiveActivityState, ...] = (),
    compensations: tuple[HarnessCompensationEntry, ...] = (),
    metadata: Mapping[str, Any] | None = None,
    max_parallelism: int = 4,
    lifecycle: str = "running",
    outcome: str = "none",
) -> HarnessGraphState:
    last_sequence = max(
        (
            0,
            *(item.last_event_sequence for item in nodes),
            *(item.dispatched_sequence for item in active_activities),
            *(item.last_event_sequence for item in compensations),
        )
    )
    return HarnessGraphState(
        run_id="run-scheduler",
        graph_ref=HarnessGraphReference(
            graph.graph_id,
            graph.workflow_ref,
            graph.schema_version,
            graph.compiler_version,
            graph.condition_policy_version,
            graph.checksum,
        ),
        lifecycle=lifecycle,
        outcome=outcome,
        node_instances=nodes,
        active_activities=active_activities,
        compensation_stack=compensations,
        budgets=HarnessGraphBudgetState(
            (
                HarnessBudgetCounterState(
                    "node_activations",
                    100,
                    used=len(nodes),
                ),
                HarnessBudgetCounterState("compensations", 100),
                HarnessBudgetCounterState("max_active_nodes", 16),
                HarnessBudgetCounterState("max_parallelism", max_parallelism),
            )
        ),
        last_event_sequence=last_sequence,
        metadata={} if metadata is None else metadata,
    )


def _running_compensation_projection(
    graph: NormalizedHarnessGraph,
    *,
    step_status: str,
    attempt: int,
    with_activity_evidence: bool,
) -> tuple[
    HarnessNodeInstanceState,
    HarnessNodeInstanceState,
    HarnessCompensationEntry,
]:
    origin_definition = _definition(graph, "publish")
    origin_identity = HarnessNodeInstanceIdentity(
        "run-scheduler",
        graph.checksum,
        "publish",
        activation_ordinal=1,
    )
    effect_ref = canonical_checksum({"effect": origin_identity.instance_id})
    origin = HarnessNodeInstanceState(
        origin_identity,
        origin_definition.node_kind,
        "succeeded",
        step_id=origin_definition.step_id,
        step_ref=origin_definition.step_ref,
        step_status="succeeded",
        attempt=1,
        evidence_refs=(
            HarnessAttemptEvidenceReference(
                effect_ref,
                HarnessEvidenceKind.SIDE_EFFECT_OUTCOME,
                origin_identity.instance_id,
                1,
                2,
                contract_ref=origin_definition.side_effect_ref,
                payload_ref=effect_ref,
            ),
        ),
        activation_sequence=1,
        last_event_sequence=2,
    )
    definition = _definition(graph, "compensation:undo-publish")
    binding = graph.compensation_refs[0]
    identity = HarnessNodeInstanceIdentity(
        "run-scheduler",
        graph.checksum,
        binding.compensation_node_id,
        activation_ordinal=2,
    )
    idempotency_key = canonical_checksum(
        {"operation": "compensate", "origin": origin.instance_id}
    )
    entry = HarnessCompensationEntry(
        "entry-publish",
        origin.instance_id,
        effect_ref,
        2,
        binding.handler_ref,
        binding.activity_ref,
        idempotency_key,
        9,
        status="running",
        compensation_node_instance_id=identity.instance_id,
        last_event_sequence=3,
    )
    evidence = ()
    if with_activity_evidence:
        result_ref = canonical_checksum(
            {"compensation": identity.instance_id, "attempt": attempt}
        )
        evidence = (
            HarnessAttemptEvidenceReference(
                result_ref,
                HarnessEvidenceKind.ACTIVITY_RESULT,
                identity.instance_id,
                attempt,
                3,
                contract_ref=definition.worker_ref,
                payload_ref=result_ref,
            ),
        )
    node = HarnessNodeInstanceState(
        identity,
        definition.node_kind,
        "compensating",
        step_id=definition.step_id,
        step_ref=definition.step_ref,
        step_status=step_status,
        attempt=attempt,
        evidence_refs=evidence,
        activation_sequence=3,
        last_event_sequence=3,
        metadata={
            "compensation_entry_id": entry.entry_id,
            "origin_node_instance_id": entry.origin_node_instance_id,
            "effect_outcome_ref": entry.effect_outcome_ref,
            "compensation_handler_ref": entry.handler_ref.exact_ref,
            "compensation_activity_ref": entry.activity_ref.exact_ref,
            "compensation_idempotency_key": entry.idempotency_key,
            "compensation_fencing_generation": entry.fencing_generation,
        },
    )
    return origin, node, entry


def _active_activity(
    graph: NormalizedHarnessGraph,
    node: HarnessNodeInstanceState,
) -> HarnessActiveActivityState:
    definition = _definition(graph, node.identity.node_id)
    return HarnessActiveActivityState(
        f"activity-{node.identity.node_id}",
        definition.activity_ref,
        node.instance_id,
        node.attempt,
        f"activity-{node.identity.node_id}:attempt:{node.attempt}",
        1,
        node.last_event_sequence,
    )


def _executable_node(
    graph: NormalizedHarnessGraph,
    node_id: str,
    *,
    status: str = "ready",
    step_status: str = "pending",
    ordinal: int,
    attempt: int = 0,
    last_sequence: int = 1,
    with_activity_evidence: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> HarnessNodeInstanceState:
    definition = _definition(graph, node_id)
    identity = HarnessNodeInstanceIdentity(
        "run-scheduler",
        graph.checksum,
        node_id,
        activation_ordinal=ordinal,
    )
    evidence = ()
    if with_activity_evidence:
        payload_ref = canonical_checksum({"worker": node_id, "attempt": attempt})
        evidence = (
            HarnessAttemptEvidenceReference(
                canonical_checksum({"activity": identity.instance_id}),
                HarnessEvidenceKind.ACTIVITY_RESULT,
                identity.instance_id,
                attempt,
                last_sequence,
                contract_ref=definition.worker_ref,
                payload_ref=payload_ref,
            ),
        )
    return HarnessNodeInstanceState(
        identity,
        definition.node_kind,
        status,
        step_id=definition.step_id,
        step_ref=definition.step_ref,
        step_status=step_status,
        attempt=attempt,
        evidence_refs=evidence,
        activation_sequence=1,
        last_event_sequence=last_sequence,
        metadata={} if metadata is None else metadata,
    )


def _control_node(
    graph: NormalizedHarnessGraph,
    node_id: str,
    *,
    ordinal: int,
) -> HarnessNodeInstanceState:
    definition = next(item for item in graph.nodes if item.node_id == node_id)
    assert isinstance(definition, HarnessControlNode)
    return HarnessNodeInstanceState(
        HarnessNodeInstanceIdentity(
            "run-scheduler",
            graph.checksum,
            node_id,
            activation_ordinal=ordinal,
        ),
        definition.node_kind,
        "ready",
        activation_sequence=1,
        last_event_sequence=1,
    )


def _step_input(
    workflow: HarnessWorkflowSpec,
    node: HarnessNodeInstanceState,
) -> HarnessGraphStepSchedulingInput:
    step = next(item for item in workflow.steps if item.step_id == node.step_id)
    return HarnessGraphStepSchedulingInput(
        node.instance_id,
        step,
        StepLifecycleObservations.for_node(node),
        _budget(),
    )


def _succeeded_worker_input(
    workflow: HarnessWorkflowSpec,
    graph: NormalizedHarnessGraph,
    node: HarnessNodeInstanceState,
    *,
    suggestions: Mapping[str, Any] | None = None,
) -> HarnessGraphStepSchedulingInput:
    del graph
    step = next(item for item in workflow.steps if item.step_id == node.step_id)
    worker = StepWorkerObservation(
        "succeeded",
        candidate_observations={} if suggestions is None else suggestions,
        accepted_evidence=node.evidence_refs[0],
    )
    return HarnessGraphStepSchedulingInput(
        node.instance_id,
        step,
        StepLifecycleObservations.for_node(node, worker_result=worker),
        _budget(),
    )


def _budget() -> StepLifecycleBudget:
    return StepLifecycleBudget(
        max_turns=20,
        turns_used=2,
        max_replans=2,
        replans_used=0,
        max_retries_per_step=2,
        max_worker_calls=20,
        worker_calls_used=1,
    )


def _definition(
    graph: NormalizedHarnessGraph,
    node_id: str,
) -> HarnessExecutableNode:
    definition = next(item for item in graph.nodes if item.node_id == node_id)
    assert isinstance(definition, HarnessExecutableNode)
    return definition
