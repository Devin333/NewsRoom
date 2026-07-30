from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from framework.harness.control_plane.decision import (
    HarnessDecision,
    HarnessDecisionType,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gates import HarnessGateResult, all_gates_passed
from framework.harness.control_plane.graph_decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.control_plane.graph_evaluator import (
    GraphEvaluation,
    HarnessGraphCandidate,
    HarnessGraphCandidateType,
    HarnessGraphEvaluationContext,
    WorkflowGraphEvaluator,
)
from framework.harness.control_plane.graph_state import (
    HarnessGraphReference,
    HarnessGraphState,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
    RunLifecycle,
)
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.control_plane.routing import HarnessRoutingEvaluator
from framework.harness.control_plane.state import (
    HarnessRunStatus,
    HarnessState,
    HarnessStepStatus,
)
from framework.harness.control_plane.step_lifecycle import (
    StepLifecycleBindingMode,
    StepLifecycleBudget,
    StepLifecycleObservations,
    StepLifecycleStateMachine,
    StepLifecycleTransition,
    StepLifecycleTransitionType,
)
from framework.harness.control_plane.transitions import (
    get_step_state,
    terminal_run_statuses,
)
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.canonical import (
    canonical_checksum,
    freeze_json,
    required_text,
    thaw_json,
)
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdgeKind,
    HarnessGraphNode,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.step import (
    HarnessRetryPolicy,
    HarnessStepSpec,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.versioning import HARNESS_WORKER_ACTIVITY_SCHEMA
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus


_STEP_GRAPH_DECISION_TYPES = MappingProxyType(
    {
        StepLifecycleTransitionType.PLAN_STEP: HarnessGraphDecisionType.ENTER_STEP_PHASE,
        StepLifecycleTransitionType.EXECUTE_STEP: HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        StepLifecycleTransitionType.VERIFY_STEP: HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        StepLifecycleTransitionType.COMPLETE_STEP: HarnessGraphDecisionType.COMPLETE_NODE,
        StepLifecycleTransitionType.RETRY_STEP: HarnessGraphDecisionType.RETRY_NODE,
        StepLifecycleTransitionType.REPLAN_STEP: HarnessGraphDecisionType.REPLAN_NODE,
        StepLifecycleTransitionType.ROUTE_TO_REPAIR: HarnessGraphDecisionType.ROUTE_TO_REPAIR,
        StepLifecycleTransitionType.WAIT_FOR_APPROVAL: HarnessGraphDecisionType.WAIT_NODE,
        StepLifecycleTransitionType.BLOCK_STEP: HarnessGraphDecisionType.WAIT_NODE,
        StepLifecycleTransitionType.FAIL_STEP: HarnessGraphDecisionType.FAIL_NODE,
        StepLifecycleTransitionType.HALT_STEP: HarnessGraphDecisionType.HALT_RUN,
    }
)
_GRAPH_RECONCILIATION_TYPES = frozenset(
    {
        HarnessGraphCandidateType.SELECT_PARALLEL_WINNER,
        HarnessGraphCandidateType.SCHEDULE_COMPENSATION,
    }
)
_CANDIDATE_ALLOWED_NODE_KINDS = MappingProxyType(
    {
        HarnessGraphCandidateType.COMPLETE_CONTROL_NODE: frozenset(
            {
                HarnessGraphNodeKind.CHOICE_JOIN,
                HarnessGraphNodeKind.LOOP_JOIN,
                HarnessGraphNodeKind.TERMINAL,
            }
        ),
        HarnessGraphCandidateType.SELECT_CHOICE: frozenset(
            {HarnessGraphNodeKind.CHOICE}
        ),
        HarnessGraphCandidateType.OPEN_FORK: frozenset(
            {HarnessGraphNodeKind.FORK_ALL, HarnessGraphNodeKind.FORK_ANY}
        ),
        HarnessGraphCandidateType.SATISFY_JOIN: frozenset(
            {HarnessGraphNodeKind.JOIN_ALL, HarnessGraphNodeKind.JOIN_ANY}
        ),
        HarnessGraphCandidateType.FAIL_JOIN: frozenset(
            {HarnessGraphNodeKind.JOIN_ALL, HarnessGraphNodeKind.JOIN_ANY}
        ),
        HarnessGraphCandidateType.SELECT_PARALLEL_WINNER: frozenset(
            {HarnessGraphNodeKind.JOIN_ANY}
        ),
        HarnessGraphCandidateType.START_LOOP_ITERATION: frozenset(
            {HarnessGraphNodeKind.LOOP_GUARD}
        ),
        HarnessGraphCandidateType.EXIT_LOOP: frozenset(
            {HarnessGraphNodeKind.LOOP_GUARD}
        ),
        HarnessGraphCandidateType.EXHAUST_LOOP: frozenset(
            {HarnessGraphNodeKind.LOOP_GUARD}
        ),
        HarnessGraphCandidateType.REGISTER_WAIT: frozenset({HarnessGraphNodeKind.WAIT}),
        HarnessGraphCandidateType.RESUME_WAIT: frozenset({HarnessGraphNodeKind.WAIT}),
        HarnessGraphCandidateType.APPLY_MERGE: frozenset({HarnessGraphNodeKind.MERGE}),
        HarnessGraphCandidateType.SCHEDULE_COMPENSATION: frozenset(
            {HarnessGraphNodeKind.EXECUTABLE}
        ),
    }
)
_GLOBAL_GRAPH_CANDIDATE_TYPES = frozenset(
    {
        HarnessGraphCandidateType.PROJECT_RUN_WAITING,
        HarnessGraphCandidateType.COMPLETE_RUN,
    }
)
_ARBITRATION_RECONCILIATION = 0
_ARBITRATION_SAFETY = 1
_ARBITRATION_STEP = 2
_ARBITRATION_GRAPH_CONTROL = 3
_ARBITRATION_ACTIVATION = 4
_ARBITRATION_WAITING = 5
_ARBITRATION_COMPLETION = 6
_STEP_LIFECYCLE_NODE_STATUSES = frozenset(
    {
        HarnessNodeInstanceStatus.READY,
        HarnessNodeInstanceStatus.RUNNING,
        HarnessNodeInstanceStatus.COMPENSATING,
    }
)


@dataclass(frozen=True, slots=True)
class HarnessGraphStepSchedulingInput:
    """Immutable, canonical input for one active executable node instance."""

    node_instance_id: str
    step: HarnessStepSpec = field(compare=False, repr=False)
    observations: StepLifecycleObservations
    budget: StepLifecycleBudget | HarnessBudgetSnapshot
    step_projection: Mapping[str, Any] = field(init=False, repr=False)
    control_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        node_instance_id = required_text(
            self.node_instance_id,
            "graph_step_scheduling_input.node_instance_id",
        )
        if not isinstance(self.step, HarnessStepSpec):
            raise TypeError("step must be HarnessStepSpec")
        if not isinstance(self.observations, StepLifecycleObservations):
            raise TypeError("observations must be StepLifecycleObservations")
        if self.observations.binding_mode is not StepLifecycleBindingMode.GRAPH_BOUND:
            raise HarnessValidationError(
                "Graph scheduling requires graph-bound Step observations",
                code="step_lifecycle_binding_mode_mismatch",
            )
        if self.observations.node_instance_id != node_instance_id:
            raise HarnessValidationError(
                "Step scheduling input belongs to another node instance",
                code="cross_node_step_observation_rejected",
            )
        if isinstance(self.budget, HarnessBudgetSnapshot):
            budget = StepLifecycleBudget.from_snapshot(self.budget)
        elif isinstance(self.budget, StepLifecycleBudget):
            budget = self.budget
        else:
            raise TypeError(
                "budget must be StepLifecycleBudget or HarnessBudgetSnapshot"
            )
        step_projection = freeze_json(
            self.step.to_dict(),
            "graph_step_scheduling_input.step",
        )
        if not isinstance(step_projection, Mapping):
            raise HarnessValidationError(
                "Step scheduling input must have a canonical object projection",
                code="invalid_graph_step_scheduling_input",
            )
        normalized_step = _step_from_projection(step_projection)
        control_projection = {
            "node_instance_id": node_instance_id,
            "step": thaw_json(step_projection),
            "observations": self.observations.control_projection(),
            "budget": budget.to_dict(),
        }
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "step", normalized_step)
        object.__setattr__(self, "budget", budget)
        object.__setattr__(self, "step_projection", step_projection)
        object.__setattr__(
            self,
            "control_checksum",
            canonical_checksum(control_projection),
        )

    def control_projection(self) -> dict[str, Any]:
        return {
            "node_instance_id": self.node_instance_id,
            "step": thaw_json(self.step_projection),
            "observations": self.observations.control_projection(),
            "budget": self.budget.to_dict(),
            "control_checksum": self.control_checksum,
        }


@dataclass(frozen=True, slots=True)
class _SchedulingOption:
    arbitration_rank: int
    stable_key: tuple[Any, ...]
    decision: HarnessGraphDecision


class HarnessScheduler:
    __slots__ = ("_graph_evaluator", "_routing", "_step_state_machine")

    def __init__(
        self,
        routing_evaluator: HarnessRoutingEvaluator | None = None,
        *,
        graph_evaluator: WorkflowGraphEvaluator | None = None,
        step_state_machine: StepLifecycleStateMachine | None = None,
    ) -> None:
        self._routing = routing_evaluator or HarnessRoutingEvaluator()
        self._graph_evaluator = graph_evaluator or WorkflowGraphEvaluator()
        self._step_state_machine = step_state_machine or StepLifecycleStateMachine()

    def next_decision(
        self,
        state: HarnessState | HarnessGraphState,
        *,
        worker_result: HarnessWorkerResult | None = None,
        quality_verdict: HarnessQualityVerdict | None = None,
        gate_results: tuple[HarnessGateResult, ...] = (),
        graph: NormalizedHarnessGraph | None = None,
        graph_context: HarnessGraphEvaluationContext | None = None,
        step_inputs: tuple[HarnessGraphStepSchedulingInput, ...] = (),
    ) -> HarnessDecision | HarnessGraphDecision | None:
        if isinstance(state, HarnessGraphState):
            if worker_result is not None or quality_verdict is not None or gate_results:
                raise HarnessValidationError(
                    "Graph scheduling accepts only graph-bound observations",
                    code="ambiguous_graph_scheduler_input",
                )
            if graph is None:
                raise HarnessValidationError(
                    "Graph scheduling requires the pinned normalized graph",
                    code="graph_scheduler_graph_missing",
                )
            return self._next_graph_decision(
                state,
                graph,
                graph_context=graph_context,
                step_inputs=step_inputs,
            )
        if not isinstance(state, HarnessState):
            raise TypeError("state must be HarnessState or HarnessGraphState")
        if graph is not None or graph_context is not None or step_inputs:
            raise HarnessValidationError(
                "Legacy scheduling cannot accept graph runtime inputs",
                code="ambiguous_graph_scheduler_input",
            )
        run_id = state.run_spec.run_id
        workflow = state.run_spec.workflow
        if state.status in terminal_run_statuses():
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=run_id,
                step_id=state.current_step_id,
                reason=f"run is already terminal: {state.status.value}",
            )

        if state.status == HarnessRunStatus.CREATED:
            return HarnessDecision(
                decision_type=HarnessDecisionType.START_STEP,
                run_id=run_id,
                step_id=workflow.entry_step_id,
                target_step_id=workflow.entry_step_id,
                reason="start entry step",
            )

        step_id = state.current_step_id or workflow.entry_step_id
        step_state = get_step_state(state, step_id)
        step_spec = _get_step_spec(workflow, step_id)

        if state.status == HarnessRunStatus.WAITING_APPROVAL:
            return HarnessDecision(
                decision_type=HarnessDecisionType.WAIT_FOR_APPROVAL,
                run_id=run_id,
                step_id=step_id,
                reason="run is waiting for Harness approval",
            )
        if step_state.status == HarnessStepStatus.PENDING:
            budget_decision = self._turn_budget_decision(state, step_id)
            if budget_decision is not None:
                return budget_decision
            return HarnessDecision(
                decision_type=HarnessDecisionType.PLAN_STEP,
                run_id=run_id,
                step_id=step_id,
            )
        if step_state.status == HarnessStepStatus.PLANNING:
            return self._after_plan(state, gate_results)
        if step_state.status == HarnessStepStatus.PLAN_VERIFIED:
            return self._execute_or_halt(state, step_id)
        if step_state.status == HarnessStepStatus.RUNNING:
            return self._after_execute(state, step_spec, worker_result)
        if step_state.status == HarnessStepStatus.RETRYING:
            return self._execute_or_halt(state, step_id, reason="retry current step")
        if step_state.status == HarnessStepStatus.VERIFYING:
            if not gate_results and quality_verdict is None:
                budget_decision = self._turn_budget_decision(state, step_id)
                if budget_decision is not None:
                    return budget_decision
                return HarnessDecision(
                    decision_type=HarnessDecisionType.VERIFY_STEP,
                    run_id=run_id,
                    step_id=step_id,
                )
            return self._after_verify(state, step_spec, gate_results, quality_verdict)
        if step_state.status == HarnessStepStatus.REPLANNING:
            budget_decision = self._turn_budget_decision(state, step_id)
            if budget_decision is not None:
                return budget_decision
            return HarnessDecision(
                decision_type=HarnessDecisionType.PLAN_STEP,
                run_id=run_id,
                step_id=step_id,
                reason="controlled replan",
            )
        if step_state.status == HarnessStepStatus.SUCCEEDED:
            return self._after_step_success(
                state, worker_result=worker_result, quality_verdict=quality_verdict
            )
        if step_state.status == HarnessStepStatus.WAITING_APPROVAL:
            return HarnessDecision(
                decision_type=HarnessDecisionType.WAIT_FOR_APPROVAL,
                run_id=run_id,
                step_id=step_id,
                reason="step is waiting for approval",
            )
        if step_state.status == HarnessStepStatus.HALTED:
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=run_id,
                step_id=step_id,
                reason=step_state.error or "step halted",
            )
        if step_state.status == HarnessStepStatus.FAILED:
            return HarnessDecision(
                decision_type=HarnessDecisionType.FAIL_RUN,
                run_id=run_id,
                step_id=step_id,
                reason=step_state.error or "step failed",
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.FAIL_RUN,
            run_id=run_id,
            step_id=step_id,
            reason=f"unsupported step status: {step_state.status.value}",
        )

    def _next_graph_decision(
        self,
        state: HarnessGraphState,
        graph: NormalizedHarnessGraph,
        *,
        graph_context: HarnessGraphEvaluationContext | None,
        step_inputs: tuple[HarnessGraphStepSchedulingInput, ...],
    ) -> HarnessGraphDecision | None:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        context = graph_context or HarnessGraphEvaluationContext()
        if not isinstance(context, HarnessGraphEvaluationContext):
            raise TypeError("graph_context must be HarnessGraphEvaluationContext")
        normalized_inputs = _normalize_graph_step_inputs(step_inputs)
        inputs_by_instance = {item.node_instance_id: item for item in normalized_inputs}
        observation_checksum = canonical_checksum(
            {
                "graph_context": context.to_dict(),
                "step_inputs": [
                    item.control_projection() for item in normalized_inputs
                ],
            }
        )
        graph_ref = _graph_reference(graph)
        if state.graph_ref != graph_ref:
            raise HarnessValidationError(
                "Graph scheduler state is pinned to another graph identity",
                code="graph_scheduler_graph_mismatch",
                details={
                    "expected": graph_ref.to_dict(),
                    "actual": state.graph_ref.to_dict(),
                },
            )
        definitions = {node.node_id: node for node in graph.nodes}
        instances = {item.instance_id: item for item in state.node_instances}
        _validate_graph_state_bindings(state, definitions)
        if state.lifecycle in {RunLifecycle.COMPLETED, RunLifecycle.HALTED}:
            if normalized_inputs:
                raise HarnessValidationError(
                    "Terminal graph state cannot accept Step scheduling inputs",
                    code="unexpected_graph_step_scheduling_input",
                )
            return None
        evaluation = self._graph_evaluator.evaluate(
            graph,
            state,
            context=context,
        )
        _validate_graph_evaluation(
            evaluation,
            graph=graph,
            state=state,
            context=context,
            definitions=definitions,
            instances=instances,
        )
        options = [
            _graph_candidate_option(
                candidate,
                graph=graph,
                state=state,
                graph_ref=graph_ref,
                observation_checksum=observation_checksum,
                definitions=definitions,
                instances=instances,
            )
            for candidate in evaluation.candidates
        ]

        step_runnable_ids: set[str] = set()
        for node_state in state.node_instances:
            definition = definitions[node_state.identity.node_id]
            if not isinstance(definition, HarnessExecutableNode):
                continue
            if node_state.status not in _STEP_LIFECYCLE_NODE_STATUSES:
                continue
            step_runnable_ids.add(node_state.instance_id)
            step_input = inputs_by_instance.get(node_state.instance_id)
            if step_input is None:
                options.append(
                    _missing_step_input_option(
                        graph_ref=graph_ref,
                        state=state,
                        node_state=node_state,
                        definition=definition,
                        observation_checksum=observation_checksum,
                    )
                )
                continue
            _validate_graph_step_input(
                graph,
                definition,
                node_state,
                step_input,
            )
            transition = self._step_state_machine.next_transition(
                step_input.step,
                node_state,
                step_input.observations,
                step_input.budget,
            )
            if transition is None or _dispatch_already_active(
                transition,
                node_state,
                state,
            ):
                continue
            options.append(
                _step_transition_option(
                    transition,
                    graph=graph,
                    state=state,
                    graph_ref=graph_ref,
                    node_state=node_state,
                    definition=definition,
                    observation_checksum=observation_checksum,
                )
            )

        extra_inputs = sorted(set(inputs_by_instance).difference(step_runnable_ids))
        if extra_inputs:
            raise HarnessValidationError(
                "Step scheduling inputs include non-runnable node instances",
                code="unexpected_graph_step_scheduling_input",
                details={"node_instance_ids": extra_inputs},
            )
        if not options:
            return None
        return min(
            options,
            key=lambda item: (
                item.arbitration_rank,
                item.stable_key,
                item.decision.decision_checksum,
            ),
        ).decision

    def _after_plan(
        self, state: HarnessState, gate_results: tuple[HarnessGateResult, ...]
    ) -> HarnessDecision:
        step_id = state.current_step_id
        if not step_id:
            return HarnessDecision(
                decision_type=HarnessDecisionType.FAIL_RUN, run_id=state.run_spec.run_id
            )
        if not gate_results or all_gates_passed(gate_results):
            return self._execute_or_halt(state, step_id)
        if self._can_replan(state):
            return HarnessDecision(
                decision_type=HarnessDecisionType.REPLAN_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="plan gate failed",
                payload={"gate_results": [result.to_dict() for result in gate_results]},
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.HALT_RUN,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason="plan gate failed and replan budget is exhausted",
            payload={
                "gate_results": [result.to_dict() for result in gate_results],
                "budget_exhausted": "replans",
            },
        )

    def _after_execute(
        self,
        state: HarnessState,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessDecision:
        step_id = step_spec.step_id
        if worker_result is None:
            return HarnessDecision(
                decision_type=HarnessDecisionType.EXECUTE_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
            )
        if worker_result.status == HarnessWorkerStatus.SUCCEEDED:
            if step_spec.metadata.get(
                "approval_required"
            ) is True and not get_step_state(state, step_id).metadata.get(
                "approval_granted"
            ):
                return HarnessDecision(
                    decision_type=HarnessDecisionType.WAIT_FOR_APPROVAL,
                    run_id=state.run_spec.run_id,
                    step_id=step_id,
                    reason="step requires Harness approval",
                )
            budget_decision = self._turn_budget_decision(state, step_id)
            if budget_decision is not None:
                return budget_decision
            return HarnessDecision(
                decision_type=HarnessDecisionType.VERIFY_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
            )
        if worker_result.status == HarnessWorkerStatus.WAITING_APPROVAL:
            if step_spec.metadata.get(
                "approval_required"
            ) is True and not get_step_state(state, step_id).metadata.get(
                "approval_granted"
            ):
                return HarnessDecision(
                    decision_type=HarnessDecisionType.WAIT_FOR_APPROVAL,
                    run_id=state.run_spec.run_id,
                    step_id=step_id,
                    reason="step requires Harness approval",
                )
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="worker requested approval without Harness policy",
            )
        if worker_result.status == HarnessWorkerStatus.BLOCKED:
            return HarnessDecision(
                decision_type=HarnessDecisionType.BLOCK_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason=worker_result.error or "worker blocked",
                payload=worker_result.to_dict(),
            )
        if self._can_retry(state, step_spec, worker_result):
            return HarnessDecision(
                decision_type=HarnessDecisionType.RETRY_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason=worker_result.error or "worker failed with retryable status",
                payload={
                    "backoff_seconds": step_spec.retry_policy.backoff_seconds,
                    "worker_result": worker_result.to_dict(),
                },
            )
        if step_spec.retry_policy.repair_step_id:
            return HarnessDecision(
                decision_type=HarnessDecisionType.ROUTE_TO_REPAIR,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                target_step_id=step_spec.retry_policy.repair_step_id,
                reason=worker_result.error
                or "worker failed; route to configured repair step",
                payload=worker_result.to_dict(),
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.FAIL_RUN,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason=worker_result.error or "worker failed and retry budget is exhausted",
            payload=worker_result.to_dict(),
        )

    def _after_verify(
        self,
        state: HarnessState,
        step_spec: HarnessStepSpec,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
    ) -> HarnessDecision:
        step_id = step_spec.step_id
        verdict_failed = quality_verdict is not None and not quality_verdict.passed
        if gate_results and all_gates_passed(gate_results) and not verdict_failed:
            return HarnessDecision(
                decision_type=HarnessDecisionType.COMPLETE_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
            )
        failed_results = [
            result.to_dict() for result in gate_results if not result.passed
        ]
        repair_step_id = (
            step_spec.retry_policy.repair_step_id
            or step_spec.metadata.get("repair_step_id")
        )
        if repair_step_id:
            return HarnessDecision(
                decision_type=HarnessDecisionType.ROUTE_TO_REPAIR,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                target_step_id=str(repair_step_id),
                reason="verification failed; route to repair step",
                payload={
                    "gate_results": failed_results,
                    "quality_verdict": _verdict_payload(quality_verdict),
                },
            )
        if self._can_replan(state):
            return HarnessDecision(
                decision_type=HarnessDecisionType.REPLAN_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="verification failed",
                payload={
                    "gate_results": failed_results,
                    "quality_verdict": _verdict_payload(quality_verdict),
                },
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.HALT_RUN,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason="verification failed and replan budget is exhausted",
            payload={
                "gate_results": failed_results,
                "quality_verdict": _verdict_payload(quality_verdict),
                "budget_exhausted": "replans",
            },
        )

    def _after_step_success(
        self,
        state: HarnessState,
        *,
        worker_result: HarnessWorkerResult | None,
        quality_verdict: HarnessQualityVerdict | None,
    ) -> HarnessDecision:
        step_id = state.current_step_id
        if not step_id:
            return HarnessDecision(
                decision_type=HarnessDecisionType.COMPLETE_RUN,
                run_id=state.run_spec.run_id,
            )
        target_step_id = self._routing.select_next_step(
            state.run_spec.workflow,
            state,
            step_id,
            worker_result=worker_result,
            quality_verdict=quality_verdict,
        )
        if target_step_id is None:
            return HarnessDecision(
                decision_type=HarnessDecisionType.COMPLETE_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="workflow has no next step",
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.ROUTE_TO_STEP,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            target_step_id=target_step_id,
            reason="explicit routing rule or workflow order selected next step",
        )

    def _execute_or_halt(
        self, state: HarnessState, step_id: str, *, reason: str | None = None
    ) -> HarnessDecision:
        budget_decision = self._turn_budget_decision(state, step_id)
        if budget_decision is not None:
            return budget_decision
        if state.worker_call_count >= state.run_spec.budget.max_worker_calls:
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="worker call budget is exhausted",
                payload={"budget_exhausted": "worker_calls"},
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.EXECUTE_STEP,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason=reason,
        )

    def _turn_budget_decision(
        self, state: HarnessState, step_id: str | None
    ) -> HarnessDecision | None:
        budget = state.run_spec.budget
        if state.turn_count >= budget.max_turns:
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="turn budget is exhausted",
                payload={
                    "turn_count": state.turn_count,
                    "max_turns": budget.max_turns,
                    "budget_exhausted": "turns",
                },
            )
        return None

    def _can_replan(self, state: HarnessState) -> bool:
        if state.current_step_id is None:
            return False
        step_state = get_step_state(state, state.current_step_id)
        return (
            state.replan_count < state.run_spec.budget.max_replans
            and step_state.replans < state.run_spec.budget.max_replans
        )

    def _can_retry(
        self,
        state: HarnessState,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult,
    ) -> bool:
        retry_policy = step_spec.retry_policy
        if worker_result.status.value not in retry_policy.retry_on_statuses:
            return False
        error_type = _error_type(worker_result)
        if error_type and error_type in retry_policy.fail_fast_error_types:
            return False
        step_state = get_step_state(state, step_spec.step_id)
        budget_attempts = state.run_spec.budget.max_retries_per_step + 1
        allowed_attempts = min(retry_policy.effective_max_attempts, budget_attempts)
        return step_state.attempts < allowed_attempts


def _normalize_graph_step_inputs(
    values: Sequence[HarnessGraphStepSchedulingInput],
) -> tuple[HarnessGraphStepSchedulingInput, ...]:
    if not isinstance(values, tuple):
        raise TypeError("step_inputs must be an immutable tuple")
    if not all(isinstance(item, HarnessGraphStepSchedulingInput) for item in values):
        raise TypeError(
            "step_inputs must contain HarnessGraphStepSchedulingInput values"
        )
    normalized = tuple(
        sorted(
            values,
            key=lambda item: (item.node_instance_id, item.control_checksum),
        )
    )
    identities = [item.node_instance_id for item in normalized]
    if len(identities) != len(set(identities)):
        raise HarnessValidationError(
            "Step scheduling inputs must be unique per node instance",
            code="duplicate_graph_step_scheduling_input",
        )
    return normalized


def _graph_reference(graph: NormalizedHarnessGraph) -> HarnessGraphReference:
    return HarnessGraphReference(
        graph.graph_id,
        graph.workflow_ref,
        graph.schema_version,
        graph.compiler_version,
        graph.condition_policy_version,
        graph.checksum,
    )


def _validate_graph_state_bindings(
    state: HarnessGraphState,
    definitions: Mapping[str, HarnessGraphNode],
) -> None:
    for node_state in state.node_instances:
        node_id = node_state.identity.node_id
        definition = definitions.get(node_id)
        if definition is None:
            raise HarnessValidationError(
                "Graph state references an unknown node definition",
                code="graph_scheduler_state_identity_mismatch",
                details={
                    "node_id": node_id,
                    "node_instance_id": node_state.instance_id,
                },
            )
        mismatches: list[str] = []
        if node_state.node_kind is not definition.node_kind:
            mismatches.append("node_kind")
        if isinstance(definition, HarnessExecutableNode):
            if node_state.step_id != definition.step_id:
                mismatches.append("step_id")
            if node_state.step_ref != definition.step_ref:
                mismatches.append("step_ref")
        if mismatches:
            raise HarnessValidationError(
                "Graph state node binding does not match its pinned definition",
                code="graph_scheduler_state_identity_mismatch",
                details={
                    "node_id": node_id,
                    "node_instance_id": node_state.instance_id,
                    "mismatches": mismatches,
                },
            )


def _validate_graph_evaluation(
    evaluation: GraphEvaluation,
    *,
    graph: NormalizedHarnessGraph,
    state: HarnessGraphState,
    context: HarnessGraphEvaluationContext,
    definitions: Mapping[str, HarnessGraphNode],
    instances: Mapping[str, HarnessNodeInstanceState],
) -> None:
    if not isinstance(evaluation, GraphEvaluation):
        raise TypeError("graph evaluator must return GraphEvaluation")
    checksum_mismatches = {
        name: {"expected": expected, "actual": actual}
        for name, expected, actual in (
            ("graph", graph.checksum, evaluation.graph_checksum),
            ("state", state.projection_checksum, evaluation.state_checksum),
            ("context", context.checksum, evaluation.context_checksum),
        )
        if expected != actual
    }
    projection_mismatches = {
        name: {"expected": list(expected), "actual": list(actual)}
        for name, expected, actual in (
            (
                "ready",
                tuple(sorted(state.ready_node_ids)),
                evaluation.ready_node_instance_ids,
            ),
            (
                "running",
                tuple(sorted(state.running_node_ids)),
                evaluation.running_node_instance_ids,
            ),
            (
                "waiting",
                tuple(sorted(state.waiting_node_ids)),
                evaluation.waiting_node_instance_ids,
            ),
            (
                "terminal",
                tuple(sorted(state.terminal_node_ids)),
                evaluation.terminal_node_instance_ids,
            ),
        )
        if expected != actual
    }
    if checksum_mismatches or projection_mismatches:
        raise HarnessValidationError(
            "Graph evaluator output does not match the accepted scheduler input",
            code="graph_scheduler_evaluation_mismatch",
            details={
                "checksums": checksum_mismatches,
                "projections": projection_mismatches,
            },
        )
    accepted_evidence_refs = _accepted_graph_candidate_evidence_refs(state, context)
    graph_branch_ids = {
        branch_id
        for branch_id in (
            *(
                branch.branch_id
                for node in graph.nodes
                if isinstance(node, HarnessControlNode)
                for branch in node.branches
            ),
            *(edge.branch_id for edge in graph.edges if edge.branch_id is not None),
            *(
                branch_id
                for node in graph.nodes
                if isinstance(node, HarnessControlNode) and node.join is not None
                for branch_id in node.join.required_branch_ids
            ),
        )
    }
    for candidate in evaluation.candidates:
        unknown_evidence_refs = sorted(
            set(candidate.evidence_refs).difference(accepted_evidence_refs)
        )
        if unknown_evidence_refs:
            raise HarnessValidationError(
                "Graph candidate references evidence outside the accepted scheduler input",
                code="graph_scheduler_candidate_evidence_mismatch",
                details={
                    "candidate_checksum": candidate.candidate_checksum,
                    "candidate_type": candidate.candidate_type.value,
                    "reason_code": candidate.reason_code,
                    "node_id": candidate.node_id,
                    "node_instance_id": candidate.node_instance_id,
                    "unaccepted_evidence_refs": unknown_evidence_refs,
                },
            )
        definition = (
            None if candidate.node_id is None else definitions.get(candidate.node_id)
        )
        if candidate.node_id is not None and definition is None:
            raise HarnessValidationError(
                "Graph candidate references an unknown node definition",
                code="graph_scheduler_candidate_identity_mismatch",
                details={"node_id": candidate.node_id},
            )
        allowed_node_kinds = _CANDIDATE_ALLOWED_NODE_KINDS.get(candidate.candidate_type)
        if allowed_node_kinds is not None and (
            definition is None or definition.node_kind not in allowed_node_kinds
        ):
            raise HarnessValidationError(
                "Graph candidate type does not match its pinned node kind",
                code="graph_scheduler_candidate_kind_mismatch",
                details={
                    "candidate_type": candidate.candidate_type.value,
                    "node_id": candidate.node_id,
                    "node_kind": (
                        None if definition is None else definition.node_kind.value
                    ),
                    "allowed_node_kinds": sorted(
                        item.value for item in allowed_node_kinds
                    ),
                },
            )
        if candidate.candidate_type in _GLOBAL_GRAPH_CANDIDATE_TYPES and (
            candidate.node_id is not None
            or candidate.node_instance_id is not None
            or candidate.target_node_ids
            or candidate.branch_id is not None
        ):
            raise HarnessValidationError(
                "Run-level graph candidate cannot carry node routing identity",
                code="graph_scheduler_candidate_kind_mismatch",
                details={"candidate_type": candidate.candidate_type.value},
            )
        if candidate.node_instance_id is not None:
            instance = instances.get(candidate.node_instance_id)
            if instance is None or (
                candidate.node_id is not None
                and instance.identity.node_id != candidate.node_id
            ):
                raise HarnessValidationError(
                    "Graph candidate references an unknown or mismatched node instance",
                    code="graph_scheduler_candidate_identity_mismatch",
                    details={
                        "node_id": candidate.node_id,
                        "node_instance_id": candidate.node_instance_id,
                    },
                )
        unknown_targets = sorted(set(candidate.target_node_ids).difference(definitions))
        if unknown_targets:
            raise HarnessValidationError(
                "Graph candidate references unknown target definitions",
                code="graph_scheduler_candidate_identity_mismatch",
                details={"target_node_ids": unknown_targets},
            )
        if (
            candidate.branch_id is not None
            and candidate.branch_id not in graph_branch_ids
        ):
            raise HarnessValidationError(
                "Graph candidate references an unknown branch",
                code="graph_scheduler_candidate_identity_mismatch",
                details={"branch_id": candidate.branch_id},
            )


def _accepted_graph_candidate_evidence_refs(
    state: HarnessGraphState,
    context: HarnessGraphEvaluationContext,
) -> frozenset[str]:
    references = {
        canonical_checksum(node_state.to_dict())
        for node_state in state.node_instances
    }
    for node_state in state.node_instances:
        for evidence in node_state.evidence_refs:
            references.add(evidence.evidence_ref)
    for join_state in state.join_states:
        references.update(join_state.terminal_event_refs.values())
    references.update(
        registration.resolution_event_ref
        for registration in state.wait_registrations
        if registration.resolution_event_ref is not None
    )
    for entry in state.compensation_stack:
        references.add(entry.effect_outcome_ref)
        if entry.outcome_ref is not None:
            references.add(entry.outcome_ref)
    if state.terminal_evidence_ref is not None:
        references.add(state.terminal_evidence_ref)
    for observation in context.observations:
        references.add(observation.evidence_ref)
        references.add(observation.payload_ref)
    return frozenset(references)


def _graph_candidate_option(
    candidate: HarnessGraphCandidate,
    *,
    graph: NormalizedHarnessGraph,
    state: HarnessGraphState,
    graph_ref: HarnessGraphReference,
    observation_checksum: str,
    definitions: Mapping[str, HarnessGraphNode],
    instances: Mapping[str, HarnessNodeInstanceState],
) -> _SchedulingOption:
    rank = _graph_candidate_rank(candidate)
    definition = (
        None if candidate.node_id is None else definitions.get(candidate.node_id)
    )
    payload = thaw_json(candidate.payload)
    if not isinstance(payload, dict):
        raise HarnessValidationError(
            "Graph candidate payload must thaw to an object",
            code="invalid_graph_candidate_payload",
        )
    payload["graph_candidate"] = {
        "checksum": candidate.candidate_checksum,
        "priority": candidate.priority,
        "branch_id": candidate.branch_id,
    }
    decision = HarnessGraphDecision(
        decision_type=HarnessGraphDecisionType(candidate.candidate_type.value),
        run_id=state.run_id,
        graph_ref=graph_ref,
        input_projection_checksum=state.projection_checksum,
        observation_checksum=observation_checksum,
        reason_code=candidate.reason_code,
        node_id=candidate.node_id,
        node_instance_id=candidate.node_instance_id,
        target_node_ids=candidate.target_node_ids,
        evidence_refs=candidate.evidence_refs,
        binding_versions=_candidate_binding_versions(
            graph,
            candidate,
            definition,
        ),
        payload=payload,
    )
    stable_key = _graph_candidate_stable_key(
        candidate,
        rank=rank,
        definition=definition,
        state=state,
        instances=instances,
    )
    return _SchedulingOption(
        rank,
        (stable_key[0], 1, stable_key[1:]),
        decision,
    )


def _graph_candidate_rank(candidate: HarnessGraphCandidate) -> int:
    if candidate.candidate_type in _GRAPH_RECONCILIATION_TYPES:
        return _ARBITRATION_RECONCILIATION
    if candidate.candidate_type is HarnessGraphCandidateType.HALT_RUN:
        return _ARBITRATION_SAFETY
    if candidate.candidate_type is HarnessGraphCandidateType.ACTIVATE_NODE:
        return _ARBITRATION_ACTIVATION
    if candidate.candidate_type is HarnessGraphCandidateType.PROJECT_RUN_WAITING:
        return _ARBITRATION_WAITING
    if candidate.candidate_type is HarnessGraphCandidateType.COMPLETE_RUN:
        return _ARBITRATION_COMPLETION
    return _ARBITRATION_GRAPH_CONTROL


def _graph_candidate_stable_key(
    candidate: HarnessGraphCandidate,
    *,
    rank: int,
    definition: HarnessGraphNode | None,
    state: HarnessGraphState,
    instances: Mapping[str, HarnessNodeInstanceState],
) -> tuple[Any, ...]:
    instance = (
        None
        if candidate.node_instance_id is None
        else instances.get(candidate.node_instance_id)
    )
    activation_ordinal = (
        2**63 - 1 if instance is None else instance.identity.activation_ordinal
    )
    declaration_order = (
        2**63 - 1 if definition is None else definition.declaration_order
    )
    if rank == _ARBITRATION_RECONCILIATION:
        return (
            _graph_candidate_causal_sequence(candidate, state, instances),
            candidate.priority,
            activation_ordinal,
            declaration_order,
            candidate.sort_key,
        )
    if rank == _ARBITRATION_ACTIVATION:
        return (declaration_order, candidate.sort_key)
    return (
        candidate.priority,
        activation_ordinal,
        declaration_order,
        candidate.sort_key,
    )


def _graph_candidate_causal_sequence(
    candidate: HarnessGraphCandidate,
    state: HarnessGraphState,
    instances: Mapping[str, HarnessNodeInstanceState],
) -> int:
    candidate_ids = (
        candidate.node_instance_id,
        candidate.payload.get("winner_node_instance_id"),
        candidate.payload.get("origin_node_instance_id"),
    )
    sequences = tuple(
        instances[item].last_event_sequence
        for item in candidate_ids
        if isinstance(item, str) and item in instances
    )
    return max(sequences) if sequences else state.last_event_sequence


def _candidate_binding_versions(
    graph: NormalizedHarnessGraph,
    candidate: HarnessGraphCandidate,
    definition: HarnessGraphNode | None,
) -> dict[str, str]:
    bindings: dict[str, str] = {}
    if isinstance(definition, HarnessExecutableNode):
        bindings.update(_step_binding_versions(definition))
    elif isinstance(definition, HarnessControlNode):
        merge_ref = None
        if definition.join is not None:
            merge_ref = definition.join.merge_ref
        if definition.merge is not None:
            merge_ref = definition.merge.merge_ref
        if merge_ref is not None:
            bindings["merge"] = merge_ref.exact_ref
    if candidate.candidate_type is HarnessGraphCandidateType.SCHEDULE_COMPENSATION:
        handler_payload = candidate.payload.get("handler_ref")
        activity_payload = candidate.payload.get("activity_ref")
        if not isinstance(handler_payload, Mapping) or not isinstance(
            activity_payload,
            Mapping,
        ):
            raise HarnessValidationError(
                "Compensation candidate is missing exact runtime bindings",
                code="graph_decision_binding_missing",
            )
        handler_ref = HarnessContractReference.from_dict(handler_payload)
        activity_ref = HarnessContractReference.from_dict(activity_payload)
        if (
            handler_ref.contract_kind is not HarnessContractKind.COMPENSATION
            or activity_ref.contract_kind is not HarnessContractKind.ACTIVITY
        ):
            raise HarnessValidationError(
                "Compensation candidate runtime binding kinds do not match",
                code="graph_decision_binding_mismatch",
            )
        bindings["compensation"] = handler_ref.exact_ref
        bindings["activity"] = activity_ref.exact_ref
    if (
        candidate.candidate_type is HarnessGraphCandidateType.COMPLETE_RUN
        and graph.terminal_policy_ref is not None
    ):
        bindings["terminal_policy"] = graph.terminal_policy_ref.exact_ref
    return bindings


def _step_transition_option(
    transition: StepLifecycleTransition,
    *,
    graph: NormalizedHarnessGraph,
    state: HarnessGraphState,
    graph_ref: HarnessGraphReference,
    node_state: HarnessNodeInstanceState,
    definition: HarnessExecutableNode,
    observation_checksum: str,
) -> _SchedulingOption:
    if transition.evidence_refs:
        rank = _ARBITRATION_RECONCILIATION
    elif transition.transition_type is StepLifecycleTransitionType.HALT_STEP:
        rank = _ARBITRATION_SAFETY
    else:
        rank = _ARBITRATION_STEP
    target_node_ids = _repair_target_node_ids(graph, definition, transition)
    decision_attempt = _step_decision_attempt(transition, node_state)
    decision = HarnessGraphDecision(
        decision_type=_STEP_GRAPH_DECISION_TYPES[transition.transition_type],
        run_id=state.run_id,
        graph_ref=graph_ref,
        input_projection_checksum=state.projection_checksum,
        observation_checksum=observation_checksum,
        reason_code=transition.reason_code,
        node_id=definition.node_id,
        node_instance_id=node_state.instance_id,
        step_ref=definition.step_ref,
        attempt=decision_attempt,
        target_node_ids=target_node_ids,
        evidence_refs=tuple(item.evidence_ref for item in transition.evidence_refs),
        binding_versions=_step_binding_versions(definition),
        payload=_step_transition_payload(
            transition,
            source_attempt=node_state.attempt,
            decision_attempt=decision_attempt,
        ),
    )
    causal_sequence = (
        max(item.event_sequence for item in transition.evidence_refs)
        if transition.evidence_refs
        else node_state.last_event_sequence
    )
    if rank == _ARBITRATION_RECONCILIATION:
        stable_key = (
            causal_sequence,
            0,
            (
                node_state.identity.activation_ordinal,
                node_state.instance_id,
                transition.transition_type.value,
                transition.reason_code,
            ),
        )
    else:
        stable_key = (
            node_state.identity.activation_ordinal,
            0,
            (
                node_state.instance_id,
                transition.transition_type.value,
                transition.reason_code,
                node_state.last_event_sequence,
            ),
        )
    return _SchedulingOption(rank, stable_key, decision)


def _missing_step_input_option(
    *,
    graph_ref: HarnessGraphReference,
    state: HarnessGraphState,
    node_state: HarnessNodeInstanceState,
    definition: HarnessExecutableNode,
    observation_checksum: str,
) -> _SchedulingOption:
    decision = HarnessGraphDecision(
        decision_type=HarnessGraphDecisionType.HALT_RUN,
        run_id=state.run_id,
        graph_ref=graph_ref,
        input_projection_checksum=state.projection_checksum,
        observation_checksum=observation_checksum,
        reason_code="step_lifecycle_input_missing",
        node_id=definition.node_id,
        node_instance_id=node_state.instance_id,
        step_ref=definition.step_ref,
        attempt=node_state.attempt,
        binding_versions=_step_binding_versions(definition),
        payload={"step_id": definition.step_id},
    )
    return _SchedulingOption(
        _ARBITRATION_SAFETY,
        (
            node_state.identity.activation_ordinal,
            0,
            (
                node_state.instance_id,
                "missing_step_input",
                decision.reason_code,
                node_state.last_event_sequence,
            ),
        ),
        decision,
    )


def _step_binding_versions(definition: HarnessExecutableNode) -> dict[str, str]:
    bindings = {
        "step": definition.step_ref.exact_ref,
        "worker": definition.worker_ref.exact_ref,
        "activity": definition.activity_ref.exact_ref,
    }
    bindings.update(
        {
            f"gate:{index:04d}": reference.exact_ref
            for index, reference in enumerate(definition.gate_refs)
        }
    )
    if definition.side_effect_ref is not None:
        bindings["side_effect"] = definition.side_effect_ref.exact_ref
    return bindings


def _repair_target_node_ids(
    graph: NormalizedHarnessGraph,
    definition: HarnessExecutableNode,
    transition: StepLifecycleTransition,
) -> tuple[str, ...]:
    if transition.transition_type is not StepLifecycleTransitionType.ROUTE_TO_REPAIR:
        return ()
    definitions = {node.node_id: node for node in graph.nodes}
    targets = tuple(
        sorted(
            edge.target_id
            for edge in graph.edges
            if edge.source_id == definition.node_id
            and edge.edge_kind is HarnessGraphEdgeKind.REPAIR
            and isinstance(definitions.get(edge.target_id), HarnessExecutableNode)
            and definitions[edge.target_id].step_id == transition.target_step_id
        )
    )
    if len(targets) != 1:
        raise HarnessValidationError(
            "Step repair transition must resolve one exact graph target",
            code="graph_repair_target_mismatch",
            details={
                "node_id": definition.node_id,
                "target_step_id": transition.target_step_id,
                "target_node_ids": list(targets),
            },
        )
    return targets


def _step_transition_payload(
    transition: StepLifecycleTransition,
    *,
    source_attempt: int,
    decision_attempt: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "step_transition_type": transition.transition_type.value,
        "reason": transition.reason,
        "source_attempt": source_attempt,
    }
    phase = {
        StepLifecycleTransitionType.PLAN_STEP: "plan",
        StepLifecycleTransitionType.EXECUTE_STEP: "execute",
        StepLifecycleTransitionType.VERIFY_STEP: "verify",
    }.get(transition.transition_type)
    if phase is not None:
        payload["phase"] = phase
    if transition.transition_type is StepLifecycleTransitionType.EXECUTE_STEP:
        payload["activity_attempt"] = decision_attempt
    if transition.target_step_id is not None:
        payload["target_step_id"] = transition.target_step_id
    for key in (
        "backoff_seconds",
        "budget_exhausted",
        "error",
        "error_type",
        "status",
    ):
        if key in transition.payload:
            payload[key] = transition.payload[key]
    return payload


def _step_decision_attempt(
    transition: StepLifecycleTransition,
    node_state: HarnessNodeInstanceState,
) -> int:
    if (
        transition.transition_type is StepLifecycleTransitionType.EXECUTE_STEP
        and node_state.step_status
        in {
            HarnessStepStatus.PLANNING,
            HarnessStepStatus.PLAN_VERIFIED,
            HarnessStepStatus.RETRYING,
        }
    ):
        return node_state.attempt + 1
    return node_state.attempt


def _dispatch_already_active(
    transition: StepLifecycleTransition,
    node_state: HarnessNodeInstanceState,
    state: HarnessGraphState,
) -> bool:
    return (
        transition.transition_type is StepLifecycleTransitionType.EXECUTE_STEP
        and any(
            item.node_instance_id == node_state.instance_id
            and item.attempt == node_state.attempt
            for item in state.active_activities
        )
    )


def _validate_graph_step_input(
    graph: NormalizedHarnessGraph,
    definition: HarnessExecutableNode,
    node_state: HarnessNodeInstanceState,
    step_input: HarnessGraphStepSchedulingInput,
) -> None:
    mismatches: list[str] = []
    step = step_input.step
    if step_input.node_instance_id != node_state.instance_id:
        mismatches.append("node_instance_id")
    if node_state.step_id != definition.step_id or step.step_id != definition.step_id:
        mismatches.append("step_id")
    if node_state.step_ref != definition.step_ref:
        mismatches.append("state.step_ref")
    expected_step_ref = HarnessContractReference(
        HarnessContractKind.STEP,
        f"{graph.workflow_id}:{step.step_id}",
        str(step.metadata.get("step_version", "1")),
    )
    if expected_step_ref != definition.step_ref:
        mismatches.append("input.step_ref")
    expected_worker_ref = HarnessContractReference(
        HarnessContractKind.WORKER,
        str(step.metadata.get("worker_id", step.step_id)),
        str(step.metadata.get("worker_version", "1")),
    )
    if expected_worker_ref != definition.worker_ref:
        mismatches.append("worker_ref")
    if _activity_reference(step) != definition.activity_ref:
        mismatches.append("activity_ref")
    if _gate_references(step) != definition.gate_refs:
        mismatches.append("gate_refs")
    expected_side_effect_ref = (
        None
        if step.side_effect_ref is None
        else HarnessContractReference(
            HarnessContractKind.SIDE_EFFECT,
            step.side_effect_ref.handler_id,
            step.side_effect_ref.version,
        )
    )
    if expected_side_effect_ref != definition.side_effect_ref:
        mismatches.append("side_effect_ref")
    if tuple(step.input_keys) != definition.input_keys:
        mismatches.append("input_keys")
    expected_outputs = () if step.output_key is None else (step.output_key,)
    if expected_outputs != definition.output_keys:
        mismatches.append("output_keys")
    if thaw_json(definition.metadata.get("step_metadata", {})) != thaw_json(
        step_input.step_projection.get("metadata", {})
    ):
        mismatches.append("step_metadata")
    if thaw_json(definition.metadata.get("retry_policy", {})) != thaw_json(
        step_input.step_projection.get("retry_policy", {})
    ):
        mismatches.append("retry_policy")
    if mismatches:
        raise HarnessValidationError(
            "Step scheduling input does not match its pinned graph definition",
            code="graph_step_scheduling_binding_mismatch",
            details={
                "node_id": definition.node_id,
                "node_instance_id": node_state.instance_id,
                "mismatches": sorted(set(mismatches)),
            },
        )


def _activity_reference(step: HarnessStepSpec) -> HarnessContractReference:
    value = str(
        step.metadata.get(
            "activity_contract_version",
            HARNESS_WORKER_ACTIVITY_SCHEMA,
        )
    ).strip()
    if value.count("@") == 1:
        contract_id, version = value.rsplit("@", maxsplit=1)
        return HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            contract_id,
            version,
        )
    if "/v" in value:
        contract_id, version_number = value.rsplit("/v", maxsplit=1)
        if contract_id and version_number.isdigit() and int(version_number) > 0:
            return HarnessContractReference(
                HarnessContractKind.ACTIVITY,
                contract_id,
                f"v{version_number}",
            )
    raise HarnessValidationError(
        "Step activity reference must be exact",
        code="graph_step_scheduling_binding_mismatch",
    )


def _gate_references(
    step: HarnessStepSpec,
) -> tuple[HarnessContractReference, ...]:
    if step.quality_gate is None:
        return ()
    value = step.quality_gate.strip()
    if value.count("@") == 1:
        gate_id, version = value.rsplit("@", maxsplit=1)
    else:
        gate_id, version = value, "1"
    return (
        HarnessContractReference(
            HarnessContractKind.GATE,
            gate_id,
            version,
        ),
    )


def _step_from_projection(value: Mapping[str, Any]) -> HarnessStepSpec:
    retry_value = value.get("retry_policy")
    if not isinstance(retry_value, Mapping):
        raise HarnessValidationError(
            "Step scheduling input retry policy must be an object",
            code="invalid_graph_step_scheduling_input",
        )
    retry_policy = HarnessRetryPolicy(
        max_retries=retry_value.get("max_retries", 0),
        max_attempts=retry_value.get("max_attempts"),
        retry_on_statuses=tuple(retry_value.get("retry_on_statuses", ())),
        backoff_seconds=retry_value.get("backoff_seconds", 0.0),
        repair_step_id=retry_value.get("repair_step_id"),
        fail_fast_error_types=tuple(retry_value.get("fail_fast_error_types", ())),
    )
    metadata = thaw_json(value.get("metadata", {}))
    if not isinstance(metadata, dict):
        raise HarnessValidationError(
            "Step scheduling input metadata must be an object",
            code="invalid_graph_step_scheduling_input",
        )
    step = HarnessStepSpec(
        step_id=value.get("step_id"),
        worker_type=value.get("worker_type"),
        input_keys=tuple(value.get("input_keys", ())),
        output_key=value.get("output_key"),
        retry_policy=retry_policy,
        quality_gate=value.get("quality_gate"),
        metadata=metadata,
        side_effect_handler=value.get("side_effect_handler"),
    )
    object.__setattr__(
        step,
        "metadata",
        freeze_json(metadata, "graph_step_scheduling_input.step.metadata"),
    )
    return step


def _get_step_spec(workflow: HarnessWorkflowSpec, step_id: str) -> HarnessStepSpec:
    for step in workflow.steps:
        if step.step_id == step_id:
            return step
    raise LookupError(step_id)


def _error_type(worker_result: HarnessWorkerResult) -> str | None:
    diagnostics = (
        worker_result.diagnostics
        if isinstance(getattr(worker_result, "diagnostics", {}), dict)
        else {}
    )
    value: Any = diagnostics.get("error_type")
    if value is None:
        value = worker_result.output.get("error_type")
    return str(value) if value is not None else None


def _verdict_payload(verdict: HarnessQualityVerdict | None) -> dict[str, Any] | None:
    return verdict.to_dict() if verdict is not None else None


__all__ = ["HarnessGraphStepSchedulingInput", "HarnessScheduler"]
