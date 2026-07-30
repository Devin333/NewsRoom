from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphActivityResultCommit,
    HarnessGraphActivityResultStatus,
    HarnessGraphCommitKind,
    HarnessGraphDecisionCommit,
    HarnessGraphProjectionCommit,
    HarnessGraphRecovery,
    HarnessGraphTransitionPort,
    graph_reference,
    initial_graph_state,
    validate_graph_activity_result,
)
from framework.harness.control_plane.graph_state import (
    HarnessActiveActivityState,
    HarnessAttemptEvidenceReference,
    HarnessEvidenceKind,
    HarnessGraphBudgetState,
    HarnessGraphState,
    HarnessJoinStatus,
    HarnessLoopIteration,
    HarnessNodeInstanceIdentity,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
    HarnessWaitStatus,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessStepStatus,
)
from framework.harness.workflow.canonical import (
    canonical_checksum,
    freeze_json,
    required_text,
    thaw_json,
)
from framework.harness.workflow.graph import (
    HarnessExecutableNode,
    HarnessGraphNode,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.validation import HarnessGraphPreflightPolicy


_CONTROL_SUCCESS_TYPES = frozenset(
    {
        HarnessGraphDecisionType.COMPLETE_CONTROL_NODE,
        HarnessGraphDecisionType.OPEN_FORK,
        HarnessGraphDecisionType.SELECT_CHOICE,
        HarnessGraphDecisionType.SATISFY_JOIN,
        HarnessGraphDecisionType.START_LOOP_ITERATION,
        HarnessGraphDecisionType.EXIT_LOOP,
        HarnessGraphDecisionType.EXHAUST_LOOP,
        HarnessGraphDecisionType.APPLY_MERGE,
        HarnessGraphDecisionType.SELECT_PARALLEL_WINNER,
    }
)
_CONTROL_FAILURE_TYPES = frozenset({HarnessGraphDecisionType.FAIL_JOIN})
_DEFERRED_CAPABILITY_TYPES = frozenset(
    {
        HarnessGraphDecisionType.REGISTER_WAIT,
        HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
        HarnessGraphDecisionType.SCHEDULE_COMPENSATION,
    }
)
_STEP_NODE_DECISION_TYPES = frozenset(
    {
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        HarnessGraphDecisionType.COMPLETE_NODE,
        HarnessGraphDecisionType.FAIL_NODE,
        HarnessGraphDecisionType.RETRY_NODE,
        HarnessGraphDecisionType.REPLAN_NODE,
        HarnessGraphDecisionType.ROUTE_TO_REPAIR,
        HarnessGraphDecisionType.WAIT_NODE,
    }
)
_RUN_DECISION_TYPES = frozenset(
    {
        HarnessGraphDecisionType.PROJECT_RUN_WAITING,
        HarnessGraphDecisionType.COMPLETE_RUN,
        HarnessGraphDecisionType.HALT_RUN,
    }
)
_CONTROL_DECISION_NODE_KINDS = MappingProxyType(
    {
        HarnessGraphDecisionType.COMPLETE_CONTROL_NODE: frozenset(
            {
                HarnessGraphNodeKind.CHOICE_JOIN,
                HarnessGraphNodeKind.LOOP_JOIN,
                HarnessGraphNodeKind.TERMINAL,
            }
        ),
        HarnessGraphDecisionType.OPEN_FORK: frozenset(
            {HarnessGraphNodeKind.FORK_ALL, HarnessGraphNodeKind.FORK_ANY}
        ),
        HarnessGraphDecisionType.SELECT_CHOICE: frozenset(
            {HarnessGraphNodeKind.CHOICE}
        ),
        HarnessGraphDecisionType.SATISFY_JOIN: frozenset(
            {HarnessGraphNodeKind.JOIN_ALL, HarnessGraphNodeKind.JOIN_ANY}
        ),
        HarnessGraphDecisionType.FAIL_JOIN: frozenset(
            {HarnessGraphNodeKind.JOIN_ALL, HarnessGraphNodeKind.JOIN_ANY}
        ),
        HarnessGraphDecisionType.SELECT_PARALLEL_WINNER: frozenset(
            {HarnessGraphNodeKind.JOIN_ANY}
        ),
        HarnessGraphDecisionType.START_LOOP_ITERATION: frozenset(
            {HarnessGraphNodeKind.LOOP_GUARD}
        ),
        HarnessGraphDecisionType.EXIT_LOOP: frozenset(
            {HarnessGraphNodeKind.LOOP_GUARD}
        ),
        HarnessGraphDecisionType.EXHAUST_LOOP: frozenset(
            {HarnessGraphNodeKind.LOOP_GUARD}
        ),
        HarnessGraphDecisionType.APPLY_MERGE: frozenset(
            {HarnessGraphNodeKind.MERGE}
        ),
    }
)
_RUNNING_CONTROL_DECISIONS = frozenset(
    {
        HarnessGraphDecisionType.SATISFY_JOIN,
        HarnessGraphDecisionType.FAIL_JOIN,
        HarnessGraphDecisionType.SELECT_PARALLEL_WINNER,
    }
)
_BUDGET_CONSUMPTIONS = MappingProxyType(
    {
        HarnessGraphDecisionType.ACTIVATE_NODE: MappingProxyType(
            {"node_activations": 1}
        ),
        HarnessGraphDecisionType.ENTER_STEP_PHASE: MappingProxyType({"turns": 1}),
        HarnessGraphDecisionType.DISPATCH_ACTIVITY: MappingProxyType(
            {"worker_calls": 1}
        ),
        HarnessGraphDecisionType.RETRY_NODE: MappingProxyType({"retries": 1}),
        HarnessGraphDecisionType.REPLAN_NODE: MappingProxyType({"replans": 1}),
    }
)


@runtime_checkable
class HarnessGraphActivityDispatcherPort(Protocol):
    def dispatch(self, activity: HarnessGraphActivity) -> None:
        """Dispatch one already committed activity descriptor."""
        ...


@dataclass(frozen=True, slots=True)
class HarnessGraphAppliedDecision:
    state: HarnessGraphState
    budget_reservations: Mapping[str, Any] = field(default_factory=dict)
    budget_consumptions: Mapping[str, Any] = field(default_factory=dict)
    activity: HarnessGraphActivity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, HarnessGraphState):
            raise TypeError("state must be HarnessGraphState")
        reservations = _freeze_counter_delta(
            self.budget_reservations,
            "budget_reservations",
        )
        consumptions = _freeze_counter_delta(
            self.budget_consumptions,
            "budget_consumptions",
        )
        if reservations != consumptions:
            raise HarnessValidationError(
                "atomic graph budget reservation must be consumed by the same transition",
                code="graph_budget_reservation_mismatch",
            )
        if self.activity is not None and not isinstance(
            self.activity,
            HarnessGraphActivity,
        ):
            raise TypeError("activity must be HarnessGraphActivity")
        object.__setattr__(self, "budget_reservations", reservations)
        object.__setattr__(self, "budget_consumptions", consumptions)


class HarnessGraphDecisionApplier:
    __slots__ = ()

    def apply(
        self,
        state: HarnessGraphState,
        graph: NormalizedHarnessGraph,
        decision: HarnessGraphDecision,
        *,
        decision_sequence: int,
        projection_sequence: int,
        activity_input_ref: str | None = None,
        accepted_evidence_refs: tuple[str, ...] = (),
    ) -> HarnessGraphAppliedDecision:
        _validate_graph_decision(
            state,
            graph,
            decision,
            accepted_evidence_refs=accepted_evidence_refs,
        )
        _positive_int(decision_sequence, "decision_sequence")
        _positive_int(projection_sequence, "projection_sequence")
        if projection_sequence != decision_sequence + 1:
            raise HarnessValidationError(
                "graph projection must immediately follow its causal decision",
                code="graph_decision_projection_sequence_mismatch",
            )
        if decision_sequence != state.last_event_sequence + 1:
            raise EventReplayMismatchError(
                sequence=state.last_event_sequence,
                reason="graph decision sequence is not contiguous with the projection",
            )
        if decision.decision_type in _DEFERRED_CAPABILITY_TYPES:
            raise HarnessValidationError(
                "graph decision requires a capability-specific durable contract",
                code="graph_decision_capability_not_enabled",
                details={"decision_type": decision.decision_type.value},
            )

        consumptions = dict(_BUDGET_CONSUMPTIONS.get(decision.decision_type, {}))
        budgets = _consume_budgets(state.budgets, consumptions)
        applied = replace(state, budgets=budgets, projection_checksum=None)
        activity: HarnessGraphActivity | None = None
        if decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE:
            applied = _activate_node(
                applied,
                graph,
                decision,
                projection_sequence=projection_sequence,
            )
        elif decision.decision_type in _STEP_NODE_DECISION_TYPES:
            applied, activity = _apply_step_decision(
                applied,
                graph,
                decision,
                decision_sequence=decision_sequence,
                projection_sequence=projection_sequence,
                activity_input_ref=activity_input_ref,
            )
        elif decision.decision_type in _CONTROL_SUCCESS_TYPES:
            applied = _apply_control_decision(
                applied,
                decision,
                projection_sequence=projection_sequence,
                succeeded=True,
            )
        elif decision.decision_type in _CONTROL_FAILURE_TYPES:
            applied = _apply_control_decision(
                applied,
                decision,
                projection_sequence=projection_sequence,
                succeeded=False,
            )
        elif decision.decision_type is HarnessGraphDecisionType.RESUME_WAIT:
            applied = _resume_wait(
                applied,
                decision,
                projection_sequence=projection_sequence,
            )
        elif decision.decision_type in _RUN_DECISION_TYPES:
            applied = _apply_run_decision(
                applied,
                decision,
                projection_sequence=projection_sequence,
            )
        else:  # pragma: no cover - enum exhaustiveness guard
            raise HarnessValidationError(
                "graph decision type has no registered Control Plane handler",
                code="unregistered_graph_decision_handler",
                details={"decision_type": decision.decision_type.value},
            )
        if applied.last_event_sequence != projection_sequence:
            applied = replace(
                applied,
                last_event_sequence=projection_sequence,
                projection_checksum=None,
            )
        return HarnessGraphAppliedDecision(
            state=applied,
            budget_reservations=consumptions,
            budget_consumptions=consumptions,
            activity=activity,
        )

    def apply_activity_result(
        self,
        state: HarnessGraphState,
        activity: HarnessGraphActivity,
        result: HarnessGraphActivityResult,
        *,
        result_sequence: int,
        projection_sequence: int,
    ) -> HarnessGraphState:
        validate_graph_activity_result(activity, result)
        _positive_int(result_sequence, "result_sequence")
        _positive_int(projection_sequence, "projection_sequence")
        if projection_sequence != result_sequence + 1:
            raise HarnessValidationError(
                "activity result projection must immediately follow its result",
                code="graph_activity_projection_sequence_mismatch",
            )
        if result_sequence != state.last_event_sequence + 1:
            raise EventReplayMismatchError(
                sequence=state.last_event_sequence,
                reason="graph activity result is not contiguous with the projection",
            )
        active = next(
            (
                item
                for item in state.active_activities
                if item.activity_id == activity.activity_id
            ),
            None,
        )
        node = _node_instance(state, activity.node_instance_id)
        mismatches: list[str] = []
        if active is None:
            mismatches.append("active_activity")
        else:
            if active.node_instance_id != node.instance_id:
                mismatches.append("node_instance_id")
            if active.attempt != result.attempt or node.attempt != result.attempt:
                mismatches.append("attempt")
            if active.idempotency_key != result.idempotency_key:
                mismatches.append("idempotency_key")
            if active.fencing_generation != result.fencing_generation:
                mismatches.append("fencing_generation")
            if active.activity_ref != result.activity_ref:
                mismatches.append("activity_ref")
        if mismatches:
            raise HarnessValidationError(
                "activity result does not match the active graph attempt",
                code="graph_activity_result_state_mismatch",
                details={"mismatches": sorted(set(mismatches))},
            )
        evidence = HarnessAttemptEvidenceReference(
            result.evidence_ref,
            HarnessEvidenceKind.ACTIVITY_RESULT,
            node.instance_id,
            result.attempt,
            result_sequence,
            contract_ref=result.activity_ref,
            payload_ref=result.payload_ref,
        )
        metadata = thaw_json(node.metadata)
        metadata.update(
            {
                "activity_result_ref": result.evidence_ref,
                "activity_result_status": result.status.value,
                "activity_payload_ref": result.payload_ref,
            }
        )
        output_refs = thaw_json(node.output_refs)
        output_refs["activity_result"] = result.payload_ref
        updated_node = replace(
            node,
            output_refs=output_refs,
            evidence_refs=(*node.evidence_refs, evidence),
            last_event_sequence=projection_sequence,
            metadata=metadata,
        )
        lifecycle = state.lifecycle
        outcome = state.outcome
        terminal_reason = state.terminal_reason_code
        terminal_evidence = state.terminal_evidence_ref
        uncertain = result.status is HarnessGraphActivityResultStatus.INDETERMINATE or (
            result.status is HarnessGraphActivityResultStatus.CANCELLED
            and not result.termination_confirmed
        )
        retain_active = uncertain and not result.termination_confirmed
        if uncertain:
            updated_node = replace(
                updated_node,
                status=HarnessNodeInstanceStatus.HALTED,
                step_status=HarnessStepStatus.HALTED,
                error_code="activity_outcome_indeterminate",
                terminal_reason="activity_outcome_indeterminate",
            )
            lifecycle = RunLifecycle.HALTED
            outcome = RunOutcome.INDETERMINATE
            terminal_reason = "activity_outcome_indeterminate"
            terminal_evidence = result.evidence_ref
        return replace(
            state,
            node_instances=_replace_node(state.node_instances, updated_node),
            active_activities=(
                state.active_activities
                if retain_active
                else tuple(
                    item
                    for item in state.active_activities
                    if item.activity_id != activity.activity_id
                )
            ),
            lifecycle=lifecycle,
            outcome=outcome,
            last_event_sequence=projection_sequence,
            terminal_reason_code=terminal_reason,
            terminal_evidence_ref=terminal_evidence,
            projection_checksum=None,
        )


class HarnessGraphControlPlaneRuntime:
    __slots__ = ("_applier", "_dispatcher", "_port")

    def __init__(
        self,
        transition_port: HarnessGraphTransitionPort,
        *,
        activity_dispatcher: HarnessGraphActivityDispatcherPort | None = None,
        applier: HarnessGraphDecisionApplier | None = None,
    ) -> None:
        if not isinstance(transition_port, HarnessGraphTransitionPort):
            raise TypeError("transition_port must implement HarnessGraphTransitionPort")
        if activity_dispatcher is not None and not isinstance(
            activity_dispatcher,
            HarnessGraphActivityDispatcherPort,
        ):
            raise TypeError(
                "activity_dispatcher must implement HarnessGraphActivityDispatcherPort"
            )
        self._port = transition_port
        self._dispatcher = activity_dispatcher
        self._applier = applier or HarnessGraphDecisionApplier()

    @property
    def transition_port(self) -> HarnessGraphTransitionPort:
        return self._port

    def initialize(
        self,
        run_spec: HarnessRunSpec,
        graph: NormalizedHarnessGraph,
        policy: HarnessGraphPreflightPolicy,
        *,
        run_spec_checksum: str,
    ) -> HarnessGraphState:
        recovery = self._port.recover_graph(run_spec.run_id)
        if recovery.state is not None:
            self._validate_recovery_identity(
                recovery,
                graph,
                expected_run_id=run_spec.run_id,
                run_spec_checksum=run_spec_checksum,
            )
            return self.recover(
                run_spec.run_id,
                graph,
                run_spec_checksum=run_spec_checksum,
            )
        if recovery.expected_last_sequence != 0:
            raise EventIncompleteHistoryError(
                "graph run stream contains history without an initial projection"
            )
        state = initial_graph_state(
            run_spec,
            graph,
            policy,
            run_spec_checksum=run_spec_checksum,
            event_sequence=1,
        )
        commit = self._port.initialize_graph(
            graph,
            state,
            run_spec_checksum=run_spec_checksum,
            occurred_at=run_spec.created_at,
            expected_last_sequence=0,
        )
        if commit.state.projection_checksum != state.projection_checksum:
            raise EventReplayMismatchError(
                sequence=commit.sequence,
                reason="graph initialization port returned a conflicting projection",
            )
        return commit.state

    def apply_decision(
        self,
        state: HarnessGraphState,
        graph: NormalizedHarnessGraph,
        decision: HarnessGraphDecision,
        *,
        run_spec_checksum: str,
        occurred_at: datetime,
        activity_input_ref: str | None = None,
        accepted_evidence_refs: tuple[str, ...] = (),
    ) -> HarnessGraphState:
        if _run_spec_checksum_from_state(state) != run_spec_checksum:
            raise EventReplayMismatchError(
                sequence=state.last_event_sequence,
                reason="graph state run spec checksum does not match the current request",
            )
        recovery = self._port.recover_graph(state.run_id)
        self._validate_recovery_identity(
            recovery,
            graph,
            expected_run_id=state.run_id,
            run_spec_checksum=run_spec_checksum,
        )
        existing = next(
            (
                item
                for item in recovery.decision_commits
                if item.decision.decision_checksum == decision.decision_checksum
            ),
            None,
        )
        if existing is not None:
            replayed = HarnessGraphDecisionCommit(
                decision,
                existing.sequence,
                existing.occurred_at,
                activity_input_ref=activity_input_ref,
                accepted_evidence_refs=accepted_evidence_refs,
            )
            if (
                replayed.decision != existing.decision
                or replayed.activity_input_ref != existing.activity_input_ref
                or replayed.accepted_evidence_refs
                != existing.accepted_evidence_refs
            ):
                raise EventStoreCorruptionError(
                    "graph decision checksum resolves conflicting request content"
                )
            projected = _projection_for_cause(
                recovery,
                decision.decision_checksum,
            )
            if projected is not None:
                if recovery.state is None:  # pragma: no cover - recovery invariant
                    raise EventIncompleteHistoryError(
                        "graph decision recovery is missing current state"
                    )
                return recovery.state
            return self._project_decision(
                recovery,
                graph,
                existing,
            )
        if recovery.pending_decisions or recovery.pending_activity_results:
            raise HarnessValidationError(
                "graph recovery must reconcile committed work before a new decision",
                code="graph_recovery_required",
            )
        if recovery.state is None or (
            recovery.state.projection_checksum != state.projection_checksum
        ):
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph decision attempted from a stale in-memory projection",
            )
        if (
            decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
            and (self._dispatcher is None or activity_input_ref is None)
        ):
            raise HarnessValidationError(
                "graph activity dispatch requires a dispatcher and durable input reference",
                code=(
                    "graph_activity_dispatcher_missing"
                    if self._dispatcher is None
                    else "graph_activity_input_ref_missing"
                ),
            )
        self._applier.apply(
            state,
            graph,
            decision,
            decision_sequence=recovery.expected_last_sequence + 1,
            projection_sequence=recovery.expected_last_sequence + 2,
            activity_input_ref=activity_input_ref,
            accepted_evidence_refs=accepted_evidence_refs,
        )
        commit = self._port.commit_graph_decision(
            decision,
            occurred_at=occurred_at,
            expected_last_sequence=recovery.expected_last_sequence,
            activity_input_ref=activity_input_ref,
            accepted_evidence_refs=accepted_evidence_refs,
        )
        refreshed = self._port.recover_graph(state.run_id)
        return self._project_decision(
            refreshed,
            graph,
            commit,
        )

    def accept_activity_result(
        self,
        result: HarnessGraphActivityResult,
        *,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        occurred_at: datetime,
    ) -> HarnessGraphState:
        if not isinstance(result, HarnessGraphActivityResult):
            raise TypeError("result must be HarnessGraphActivityResult")
        activity = self._port.activity_for(result.activity_id)
        if activity is None:
            raise HarnessValidationError(
                "graph activity result references an unknown activity",
                code="graph_activity_identity_mismatch",
            )
        recovery = self._port.recover_graph(activity.run_id)
        self._validate_recovery_identity(
            recovery,
            graph,
            expected_run_id=activity.run_id,
            run_spec_checksum=run_spec_checksum,
        )
        existing = next(
            (
                item
                for item in recovery.activity_result_commits
                if item.result.activity_id == result.activity_id
            ),
            None,
        )
        if existing is not None:
            if existing.result != result:
                raise EventReplayMismatchError(
                    sequence=existing.sequence,
                    reason="graph activity produced a conflicting duplicate result",
                )
            projected = _projection_for_cause(recovery, result.result_checksum)
            if projected is not None:
                if recovery.state is None:  # pragma: no cover - recovery invariant
                    raise EventIncompleteHistoryError(
                        "graph activity result recovery is missing current state"
                    )
                return recovery.state
            return self._project_activity_result(recovery, activity, existing)
        if recovery.pending_decisions or recovery.pending_activity_results:
            raise HarnessValidationError(
                "graph recovery must reconcile committed work before accepting a result",
                code="graph_recovery_required",
            )
        validate_graph_activity_result(activity, result)
        if recovery.state is None:
            raise EventIncompleteHistoryError("graph activity result is missing state")
        self._applier.apply_activity_result(
            recovery.state,
            activity,
            result,
            result_sequence=recovery.expected_last_sequence + 1,
            projection_sequence=recovery.expected_last_sequence + 2,
        )
        commit = self._port.commit_graph_activity_result(
            result,
            occurred_at=occurred_at,
            expected_last_sequence=recovery.expected_last_sequence,
        )
        refreshed = self._port.recover_graph(activity.run_id)
        return self._project_activity_result(refreshed, activity, commit)

    def recover(
        self,
        run_id: str,
        graph: NormalizedHarnessGraph,
        *,
        run_spec_checksum: str,
    ) -> HarnessGraphState:
        run_id = required_text(run_id, "run_id")
        while True:
            recovery = self._port.recover_graph(run_id)
            self._validate_recovery_identity(
                recovery,
                graph,
                expected_run_id=run_id,
                run_spec_checksum=run_spec_checksum,
            )
            pending = tuple(
                sorted(
                    (
                        *(('decision', item.sequence, item) for item in recovery.pending_decisions),
                        *(
                            ('result', item.sequence, item)
                            for item in recovery.pending_activity_results
                        ),
                    ),
                    key=lambda item: item[1],
                )
            )
            if not pending:
                break
            if len(pending) != 1:
                raise EventIncompleteHistoryError(
                    "graph run contains multiple unprojected causal records"
                )
            kind, _, commit = pending[0]
            if kind == "decision":
                if not isinstance(commit, HarnessGraphDecisionCommit):
                    raise EventIncompleteHistoryError(
                        "graph pending decision record is invalid"
                    )
                self._project_decision(
                    recovery,
                    graph,
                    commit,
                )
            else:
                if not isinstance(commit, HarnessGraphActivityResultCommit):
                    raise EventIncompleteHistoryError(
                        "graph pending activity result record is invalid"
                    )
                activity = self._port.activity_for(commit.result.activity_id)
                if activity is None:
                    raise EventIncompleteHistoryError(
                        "graph activity result is missing its durable descriptor"
                    )
                self._project_activity_result(recovery, activity, commit)
        recovery = self._port.recover_graph(run_id)
        state = recovery.state
        if state is None:
            raise EventIncompleteHistoryError("graph run has no durable state")
        result_activity_ids = {
            item.result.activity_id for item in recovery.activity_result_commits
        }
        active_activity_ids = {
            item.activity_id for item in state.active_activities
        }
        for activity in recovery.activities:
            if (
                activity.activity_id not in active_activity_ids
                or
                activity.activity_id in result_activity_ids
                or activity.activity_id in recovery.dispatched_activity_ids
            ):
                continue
            self._dispatch_after_commit(activity)
        return self._port.recover_graph(run_id).state or state

    def _project_decision(
        self,
        recovery: HarnessGraphRecovery,
        graph: NormalizedHarnessGraph,
        commit: HarnessGraphDecisionCommit,
    ) -> HarnessGraphState:
        state = recovery.state
        if state is None:
            raise EventIncompleteHistoryError(
                "graph decision cannot project without an initialized state"
            )
        if recovery.expected_last_sequence != commit.sequence:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph decision projection does not follow its causal commit",
            )
        applied = self._applier.apply(
            state,
            graph,
            commit.decision,
            decision_sequence=commit.sequence,
            projection_sequence=commit.sequence + 1,
            activity_input_ref=commit.activity_input_ref,
            accepted_evidence_refs=commit.accepted_evidence_refs,
        )
        projection = HarnessGraphProjectionCommit(
            HarnessGraphCommitKind.DECISION_PROJECTION,
            commit.decision.decision_checksum,
            state.projection_checksum,
            applied.state,
            commit.sequence + 1,
            commit.occurred_at,
            budget_reservations=applied.budget_reservations,
            budget_consumptions=applied.budget_consumptions,
            activity=applied.activity,
        )
        committed = self._port.commit_graph_projection(
            projection,
            expected_last_sequence=commit.sequence,
        )
        if committed != projection:
            raise EventReplayMismatchError(
                sequence=committed.sequence,
                reason="graph transition port returned a conflicting projection",
            )
        if applied.activity is not None:
            self._dispatch_after_commit(applied.activity)
        return committed.state

    def _project_activity_result(
        self,
        recovery: HarnessGraphRecovery,
        activity: HarnessGraphActivity,
        commit: HarnessGraphActivityResultCommit,
    ) -> HarnessGraphState:
        state = recovery.state
        if state is None:
            raise EventIncompleteHistoryError(
                "graph activity result cannot project without state"
            )
        if recovery.expected_last_sequence != commit.sequence:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="activity result projection does not follow its causal commit",
            )
        projected = self._applier.apply_activity_result(
            state,
            activity,
            commit.result,
            result_sequence=commit.sequence,
            projection_sequence=commit.sequence + 1,
        )
        projection = HarnessGraphProjectionCommit(
            HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION,
            commit.result.result_checksum,
            state.projection_checksum,
            projected,
            commit.sequence + 1,
            commit.occurred_at,
        )
        committed = self._port.commit_graph_projection(
            projection,
            expected_last_sequence=commit.sequence,
        )
        if committed != projection:
            raise EventReplayMismatchError(
                sequence=committed.sequence,
                reason="graph transition port returned a conflicting result projection",
            )
        return committed.state

    def _dispatch_after_commit(self, activity: HarnessGraphActivity) -> None:
        if self._dispatcher is None:
            raise HarnessValidationError(
                "graph activity dispatch requires an injected dispatcher",
                code="graph_activity_dispatcher_missing",
            )
        self._dispatcher.dispatch(activity)
        self._port.mark_activity_dispatched(activity.activity_id)

    @staticmethod
    def _validate_recovery_identity(
        recovery: HarnessGraphRecovery,
        graph: NormalizedHarnessGraph,
        *,
        expected_run_id: str,
        run_spec_checksum: str,
    ) -> None:
        if recovery.run_id != expected_run_id:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="recovered graph run id does not match the requested run",
            )
        if recovery.graph != graph:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="recovered graph does not match the pinned graph",
            )
        if recovery.run_spec_checksum != run_spec_checksum:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="recovered graph run spec checksum does not match",
            )
        if recovery.state is None:
            raise EventIncompleteHistoryError("graph recovery is missing its state")
        if recovery.state.graph_ref != graph_reference(graph):
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="recovered graph state reference does not match",
            )


def _validate_graph_decision(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
    decision: HarnessGraphDecision,
    *,
    accepted_evidence_refs: tuple[str, ...],
) -> None:
    if not isinstance(state, HarnessGraphState):
        raise TypeError("state must be HarnessGraphState")
    if not isinstance(graph, NormalizedHarnessGraph):
        raise TypeError("graph must be NormalizedHarnessGraph")
    if not isinstance(decision, HarnessGraphDecision):
        raise TypeError("decision must be HarnessGraphDecision")
    if state.lifecycle in {RunLifecycle.COMPLETED, RunLifecycle.HALTED}:
        raise HarnessValidationError(
            "terminal graph state cannot accept another decision",
            code="graph_control_terminal_state",
        )
    mismatches: list[str] = []
    if decision.run_id != state.run_id:
        mismatches.append("run_id")
    if decision.graph_ref != state.graph_ref or decision.graph_ref != graph_reference(graph):
        mismatches.append("graph_ref")
    if decision.input_projection_checksum != state.projection_checksum:
        mismatches.append("input_projection_checksum")
    definitions = {item.node_id: item for item in graph.nodes}
    instances = {item.instance_id: item for item in state.node_instances}
    definition = None if decision.node_id is None else definitions.get(decision.node_id)
    if decision.node_id is not None and definition is None:
        mismatches.append("node_id")
    instance = (
        None
        if decision.node_instance_id is None
        else instances.get(decision.node_instance_id)
    )
    if decision.node_instance_id is not None and (
        instance is None
        or decision.node_id is None
        or instance.identity.node_id != decision.node_id
    ):
        mismatches.append("node_instance_id")
    if set(decision.target_node_ids).difference(definitions):
        mismatches.append("target_node_ids")
    if (
        isinstance(definition, HarnessExecutableNode)
        and decision.decision_type
        is not HarnessGraphDecisionType.SCHEDULE_COMPENSATION
    ):
        expected_bindings = _executable_binding_versions(definition)
        if dict(decision.binding_versions) != expected_bindings:
            mismatches.append("binding_versions")
        if decision.step_ref is not None and decision.step_ref != definition.step_ref:
            mismatches.append("step_ref")
    if mismatches:
        raise HarnessValidationError(
            "graph decision does not match the current pinned projection",
            code="graph_control_decision_mismatch",
            details={"mismatches": sorted(set(mismatches))},
        )
    allowed_evidence = _state_evidence_refs(state).union(
        _checksum_tuple(accepted_evidence_refs, "accepted_evidence_refs")
    )
    unaccepted = tuple(
        ref for ref in decision.evidence_refs if ref not in allowed_evidence
    )
    if unaccepted:
        raise HarnessValidationError(
            "graph decision references evidence outside accepted Control Plane inputs",
            code="graph_control_decision_evidence_mismatch",
            details={"unaccepted_evidence_refs": list(unaccepted)},
        )


def _activate_node(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
    decision: HarnessGraphDecision,
    *,
    projection_sequence: int,
) -> HarnessGraphState:
    if decision.node_id is None:
        raise HarnessValidationError(
            "node activation requires a node definition",
            code="graph_activation_identity_missing",
        )
    definition = _definition(graph, decision.node_id)
    max_active_nodes = state.budgets.require("max_active_nodes").limit
    active_node_count = sum(not item.is_terminal for item in state.node_instances)
    if active_node_count >= max_active_nodes:
        raise HarnessValidationError(
            "graph node activation exceeds active-node capacity",
            code="graph_active_node_limit_exceeded",
            details={"active": active_node_count, "limit": max_active_nodes},
        )
    branch_path = tuple(decision.payload.get("branch_path", ()))
    raw_vector = decision.payload.get("iteration_vector", ())
    if not isinstance(raw_vector, tuple | list):
        raise HarnessValidationError(
            "activation iteration_vector must be an array",
            code="invalid_graph_activation_scope",
        )
    iteration_vector = tuple(
        HarnessLoopIteration.from_dict(item) for item in raw_vector
    )
    if any(
        item.identity.node_id == definition.node_id
        and item.identity.branch_path == branch_path
        and item.identity.iteration_vector == iteration_vector
        for item in state.node_instances
    ):
        raise HarnessValidationError(
            "graph node scope is already activated",
            code="duplicate_graph_node_activation",
        )
    ordinal = max(
        (item.identity.activation_ordinal for item in state.node_instances),
        default=0,
    ) + 1
    identity = HarnessNodeInstanceIdentity(
        state.run_id,
        graph.checksum,
        definition.node_id,
        branch_path=branch_path,
        iteration_vector=iteration_vector,
        activation_ordinal=ordinal,
    )
    common = {
        "identity": identity,
        "node_kind": definition.node_kind,
        "status": HarnessNodeInstanceStatus.READY,
        "activation_sequence": projection_sequence,
        "last_event_sequence": projection_sequence,
        "metadata": _decision_metadata(decision),
    }
    if isinstance(definition, HarnessExecutableNode):
        node = HarnessNodeInstanceState(
            **common,
            step_id=definition.step_id,
            step_ref=definition.step_ref,
            step_status=HarnessStepStatus.PENDING,
        )
    else:
        node = HarnessNodeInstanceState(**common)
    lifecycle = (
        RunLifecycle.RUNNING
        if state.lifecycle is RunLifecycle.CREATED
        else state.lifecycle
    )
    return replace(
        state,
        lifecycle=lifecycle,
        node_instances=(*state.node_instances, node),
        last_event_sequence=projection_sequence,
        projection_checksum=None,
    )


def _apply_step_decision(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
    decision: HarnessGraphDecision,
    *,
    decision_sequence: int,
    projection_sequence: int,
    activity_input_ref: str | None,
) -> tuple[HarnessGraphState, HarnessGraphActivity | None]:
    if decision.node_instance_id is None or decision.node_id is None:
        raise HarnessValidationError(
            "Step decision requires node identity",
            code="graph_step_decision_identity_missing",
        )
    node = _node_instance(state, decision.node_instance_id)
    definition = _definition(graph, decision.node_id)
    if not isinstance(definition, HarnessExecutableNode):
        raise HarnessValidationError(
            "Step decision requires an executable definition",
            code="graph_step_decision_node_kind_mismatch",
        )
    decision_type = decision.decision_type
    _validate_step_decision_source(node, decision_type)
    expected_attempt = (
        node.attempt + 1
        if decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
        and node.step_status
        in {
            HarnessStepStatus.PLANNING,
            HarnessStepStatus.PLAN_VERIFIED,
            HarnessStepStatus.RETRYING,
        }
        else node.attempt
    )
    if decision.attempt != expected_attempt:
        raise HarnessValidationError(
            "graph Step decision does not match the current attempt",
            code="graph_step_decision_attempt_mismatch",
            details={
                "decision_type": decision_type.value,
                "expected_attempt": expected_attempt,
                "actual_attempt": decision.attempt,
            },
        )
    activity: HarnessGraphActivity | None = None
    metadata = _merged_node_metadata(node, decision)
    status = HarnessNodeInstanceStatus.RUNNING
    step_status = node.step_status
    attempt = node.attempt
    replans = node.replans
    error_code = node.error_code
    terminal_reason = node.terminal_reason
    active_activities = state.active_activities
    if decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE:
        step_status = HarnessStepStatus.PLANNING
    elif decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY:
        if activity_input_ref is None:
            raise HarnessValidationError(
                "activity dispatch requires a durable input reference",
                code="graph_activity_input_ref_missing",
            )
        if decision.attempt is None:
            raise HarnessValidationError(
                "activity dispatch requires an attempt",
                code="graph_step_decision_identity_missing",
            )
        max_parallelism = state.budgets.require("max_parallelism")
        if len(state.active_activities) >= max_parallelism.limit:
            raise HarnessValidationError(
                "graph activity dispatch exceeds physical parallelism",
                code="graph_parallelism_exceeded",
                details={"limit": max_parallelism.limit},
            )
        if any(item.node_instance_id == node.instance_id for item in active_activities):
            raise HarnessValidationError(
                "node instance already has an active activity",
                code="duplicate_active_activity_attempt",
            )
        attempt = decision.attempt
        fencing_generation = int(metadata.get("fencing_generation", 0)) + 1
        metadata["fencing_generation"] = fencing_generation
        activity = HarnessGraphActivity(
            run_id=state.run_id,
            graph_ref=state.graph_ref,
            node_id=definition.node_id,
            node_instance_id=node.instance_id,
            step_ref=definition.step_ref,
            worker_ref=definition.worker_ref,
            activity_ref=definition.activity_ref,
            attempt=attempt,
            input_ref=activity_input_ref,
            causal_decision_checksum=decision.decision_checksum,
            causal_decision_sequence=decision_sequence,
            fencing_generation=fencing_generation,
            tenant_scope_ref=state.metadata.get("tenant_scope_ref"),
            identity_scope_ref=state.metadata.get("identity_scope_ref"),
            subject_scope_ref=state.metadata.get("subject_scope_ref"),
        )
        active_activities = (
            *active_activities,
            HarnessActiveActivityState(
                activity.activity_id,
                activity.activity_ref,
                activity.node_instance_id,
                activity.attempt,
                activity.idempotency_key,
                activity.fencing_generation,
                decision_sequence,
            ),
        )
        step_status = HarnessStepStatus.RUNNING
    elif decision_type is HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT:
        step_status = HarnessStepStatus.VERIFYING
    elif decision_type is HarnessGraphDecisionType.COMPLETE_NODE:
        status = HarnessNodeInstanceStatus.SUCCEEDED
        step_status = HarnessStepStatus.SUCCEEDED
    elif decision_type is HarnessGraphDecisionType.FAIL_NODE:
        status = HarnessNodeInstanceStatus.FAILED
        step_status = HarnessStepStatus.FAILED
        error_code = decision.reason_code
        terminal_reason = decision.reason_code
    elif decision_type is HarnessGraphDecisionType.RETRY_NODE:
        step_status = HarnessStepStatus.RETRYING
    elif decision_type is HarnessGraphDecisionType.REPLAN_NODE:
        step_status = HarnessStepStatus.REPLANNING
        replans += 1
    elif decision_type is HarnessGraphDecisionType.ROUTE_TO_REPAIR:
        status = HarnessNodeInstanceStatus.FAILED
        step_status = HarnessStepStatus.FAILED
        error_code = decision.reason_code
        terminal_reason = decision.reason_code
    elif decision_type is HarnessGraphDecisionType.WAIT_NODE:
        status = HarnessNodeInstanceStatus.WAITING
        step_status = HarnessStepStatus.WAITING_APPROVAL
    else:  # pragma: no cover - caller dispatches only Step decisions
        raise AssertionError(f"unexpected Step decision: {decision_type.value}")
    updated = replace(
        node,
        status=status,
        step_status=step_status,
        attempt=attempt,
        replans=replans,
        error_code=error_code,
        terminal_reason=terminal_reason,
        last_event_sequence=projection_sequence,
        metadata=metadata,
    )
    return (
        replace(
            state,
            lifecycle=(
                RunLifecycle.RUNNING
                if state.lifecycle is RunLifecycle.CREATED
                else state.lifecycle
            ),
            node_instances=_replace_node(state.node_instances, updated),
            active_activities=active_activities,
            last_event_sequence=projection_sequence,
            projection_checksum=None,
        ),
        activity,
    )


def _apply_control_decision(
    state: HarnessGraphState,
    decision: HarnessGraphDecision,
    *,
    projection_sequence: int,
    succeeded: bool,
) -> HarnessGraphState:
    if decision.node_instance_id is None:
        raise HarnessValidationError(
            "control decision requires a node instance",
            code="graph_control_node_identity_missing",
        )
    node = _node_instance(state, decision.node_instance_id)
    allowed_kinds = _CONTROL_DECISION_NODE_KINDS[decision.decision_type]
    if node.node_kind not in allowed_kinds:
        raise HarnessValidationError(
            "control decision targets an incompatible node kind",
            code="graph_control_node_kind_mismatch",
            details={
                "decision_type": decision.decision_type.value,
                "node_kind": node.node_kind.value,
                "allowed_node_kinds": sorted(item.value for item in allowed_kinds),
            },
        )
    expected_status = (
        HarnessNodeInstanceStatus.RUNNING
        if decision.decision_type in _RUNNING_CONTROL_DECISIONS
        else HarnessNodeInstanceStatus.READY
    )
    if node.status is not expected_status:
        raise HarnessValidationError(
            "control decision is incompatible with the current node status",
            code="graph_control_node_state_mismatch",
            details={
                "decision_type": decision.decision_type.value,
                "node_status": node.status.value,
                "expected_status": expected_status.value,
            },
        )
    status = (
        HarnessNodeInstanceStatus.SUCCEEDED
        if succeeded
        else HarnessNodeInstanceStatus.FAILED
    )
    updated = replace(
        node,
        status=status,
        error_code=None if succeeded else decision.reason_code,
        terminal_reason=None if succeeded else decision.reason_code,
        last_event_sequence=projection_sequence,
        metadata=_merged_node_metadata(node, decision),
    )
    joins = state.join_states
    if decision.decision_type in {
        HarnessGraphDecisionType.SATISFY_JOIN,
        HarnessGraphDecisionType.FAIL_JOIN,
        HarnessGraphDecisionType.SELECT_PARALLEL_WINNER,
    }:
        join = next(
            (
                item
                for item in joins
                if item.join_instance_id == decision.node_instance_id
            ),
            None,
        )
        if join is not None:
            winner = join.winner_branch_id
            if decision.decision_type is HarnessGraphDecisionType.SELECT_PARALLEL_WINNER:
                graph_candidate = decision.payload.get("graph_candidate", {})
                if isinstance(graph_candidate, Mapping):
                    winner = graph_candidate.get("branch_id")
            join_status = (
                HarnessJoinStatus.FAILED
                if decision.decision_type is HarnessGraphDecisionType.FAIL_JOIN
                else HarnessJoinStatus.SATISFIED
            )
            updated_join = replace(
                join,
                status=join_status,
                winner_branch_id=winner,
                last_event_sequence=projection_sequence,
            )
            joins = tuple(
                updated_join if item.join_instance_id == join.join_instance_id else item
                for item in joins
            )
    return replace(
        state,
        node_instances=_replace_node(state.node_instances, updated),
        join_states=joins,
        last_event_sequence=projection_sequence,
        projection_checksum=None,
    )


def _resume_wait(
    state: HarnessGraphState,
    decision: HarnessGraphDecision,
    *,
    projection_sequence: int,
) -> HarnessGraphState:
    if decision.node_instance_id is None:
        raise HarnessValidationError(
            "Wait resume requires a node instance",
            code="graph_control_node_identity_missing",
        )
    node = _node_instance(state, decision.node_instance_id)
    if (
        node.node_kind is not HarnessGraphNodeKind.WAIT
        or node.status is not HarnessNodeInstanceStatus.WAITING
    ):
        raise HarnessValidationError(
            "Wait resume targets an incompatible node state",
            code="graph_wait_node_state_mismatch",
        )
    registration = next(
        (
            item
            for item in state.wait_registrations
            if item.node_instance_id == node.instance_id
        ),
        None,
    )
    if registration is None or registration.status is HarnessWaitStatus.REGISTERED:
        raise HarnessValidationError(
            "Wait resume requires durable resolution evidence",
            code="graph_wait_resolution_missing",
        )
    status = (
        HarnessNodeInstanceStatus.FAILED
        if registration.status is HarnessWaitStatus.TIMED_OUT
        and not decision.target_node_ids
        else HarnessNodeInstanceStatus.SUCCEEDED
    )
    updated = replace(
        node,
        status=status,
        error_code=(
            "wait_timed_out" if status is HarnessNodeInstanceStatus.FAILED else None
        ),
        terminal_reason=(
            "wait_timed_out" if status is HarnessNodeInstanceStatus.FAILED else None
        ),
        last_event_sequence=projection_sequence,
        metadata=_merged_node_metadata(node, decision),
    )
    return replace(
        state,
        lifecycle=RunLifecycle.RUNNING,
        node_instances=_replace_node(state.node_instances, updated),
        last_event_sequence=projection_sequence,
        projection_checksum=None,
    )


def _apply_run_decision(
    state: HarnessGraphState,
    decision: HarnessGraphDecision,
    *,
    projection_sequence: int,
) -> HarnessGraphState:
    if decision.decision_type is HarnessGraphDecisionType.PROJECT_RUN_WAITING:
        return replace(
            state,
            lifecycle=RunLifecycle.WAITING,
            last_event_sequence=projection_sequence,
            projection_checksum=None,
        )
    if decision.decision_type is HarnessGraphDecisionType.COMPLETE_RUN:
        outcome_value = decision.payload.get("outcome", RunOutcome.SUCCEEDED.value)
        outcome = RunOutcome(outcome_value)
        return replace(
            state,
            lifecycle=RunLifecycle.COMPLETED,
            outcome=outcome,
            last_event_sequence=projection_sequence,
            projection_checksum=None,
        )
    node_instances = state.node_instances
    if decision.node_instance_id is not None:
        node = _node_instance(state, decision.node_instance_id)
        has_active_activity = any(
            item.node_instance_id == node.instance_id
            for item in state.active_activities
        )
        if has_active_activity:
            node = replace(
                node,
                status=HarnessNodeInstanceStatus.CANCEL_REQUESTED,
                error_code=decision.reason_code,
                terminal_reason=decision.reason_code,
                last_event_sequence=projection_sequence,
            )
        elif node.node_kind is HarnessGraphNodeKind.EXECUTABLE:
            node = replace(
                node,
                status=HarnessNodeInstanceStatus.HALTED,
                step_status=HarnessStepStatus.HALTED,
                error_code=decision.reason_code,
                terminal_reason=decision.reason_code,
                last_event_sequence=projection_sequence,
            )
        else:
            node = replace(
                node,
                status=HarnessNodeInstanceStatus.HALTED,
                error_code=decision.reason_code,
                terminal_reason=decision.reason_code,
                last_event_sequence=projection_sequence,
            )
        node_instances = _replace_node(node_instances, node)
    requested_outcome = decision.payload.get("outcome")
    outcome = RunOutcome.NONE if requested_outcome is None else RunOutcome(requested_outcome)
    evidence_ref = (
        decision.evidence_refs[0]
        if outcome is RunOutcome.INDETERMINATE and decision.evidence_refs
        else None
    )
    return replace(
        state,
        lifecycle=RunLifecycle.HALTED,
        outcome=outcome,
        node_instances=node_instances,
        last_event_sequence=projection_sequence,
        terminal_reason_code=decision.reason_code,
        terminal_evidence_ref=evidence_ref,
        projection_checksum=None,
    )


def _consume_budgets(
    budgets: HarnessGraphBudgetState,
    consumptions: Mapping[str, int],
) -> HarnessGraphBudgetState:
    if not consumptions:
        return budgets
    updated = []
    for counter in budgets.counters:
        amount = consumptions.get(counter.name, 0)
        if amount:
            if counter.remaining < amount:
                raise HarnessValidationError(
                    "graph budget is exhausted",
                    code="graph_budget_exhausted",
                    details={
                        "name": counter.name,
                        "limit": counter.limit,
                        "used": counter.used,
                        "reserved": counter.reserved,
                        "requested": amount,
                    },
                )
            counter = replace(counter, used=counter.used + amount)
        updated.append(counter)
    missing = sorted(set(consumptions).difference(item.name for item in budgets.counters))
    if missing:
        raise HarnessValidationError(
            "graph budget counter is missing",
            code="graph_budget_counter_missing",
            details={"names": missing},
        )
    return HarnessGraphBudgetState(tuple(updated))


def _validate_step_decision_source(
    node: HarnessNodeInstanceState,
    decision_type: HarnessGraphDecisionType,
) -> None:
    allowed = {
        HarnessGraphDecisionType.ENTER_STEP_PHASE: frozenset(
            {
                (HarnessNodeInstanceStatus.READY, HarnessStepStatus.PENDING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.REPLANNING),
            }
        ),
        HarnessGraphDecisionType.DISPATCH_ACTIVITY: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.PLANNING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.PLAN_VERIFIED),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RETRYING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.PLANNING),
                (
                    HarnessNodeInstanceStatus.COMPENSATING,
                    HarnessStepStatus.PLAN_VERIFIED,
                ),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.RETRYING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.RUNNING),
            }
        ),
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.RUNNING),
            }
        ),
        HarnessGraphDecisionType.COMPLETE_NODE: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.VERIFYING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.VERIFYING),
            }
        ),
        HarnessGraphDecisionType.FAIL_NODE: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.VERIFYING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.VERIFYING),
            }
        ),
        HarnessGraphDecisionType.RETRY_NODE: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.VERIFYING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.VERIFYING),
            }
        ),
        HarnessGraphDecisionType.REPLAN_NODE: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.PLANNING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.VERIFYING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.PLANNING),
                (HarnessNodeInstanceStatus.COMPENSATING, HarnessStepStatus.VERIFYING),
            }
        ),
        HarnessGraphDecisionType.ROUTE_TO_REPAIR: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.VERIFYING),
            }
        ),
        HarnessGraphDecisionType.WAIT_NODE: frozenset(
            {
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.RUNNING),
                (HarnessNodeInstanceStatus.RUNNING, HarnessStepStatus.VERIFYING),
            }
        ),
    }[decision_type]
    current = (node.status, node.step_status)
    if current not in allowed:
        raise HarnessValidationError(
            "graph Step decision is incompatible with the current node phase",
            code="graph_step_decision_state_mismatch",
            details={
                "decision_type": decision_type.value,
                "node_status": node.status.value,
                "step_status": None if node.step_status is None else node.step_status.value,
            },
        )


def _decision_metadata(decision: HarnessGraphDecision) -> dict[str, Any]:
    metadata = {
        "last_decision_checksum": decision.decision_checksum,
        "last_reason_code": decision.reason_code,
        "last_decision_type": decision.decision_type.value,
        "decision_payload": thaw_json(decision.payload),
        "target_node_ids": list(decision.target_node_ids),
    }
    if decision.decision_type is HarnessGraphDecisionType.OPEN_FORK:
        branches = decision.payload.get("branches", ())
        if isinstance(branches, tuple):
            metadata["opened_branch_ids"] = [
                item.get("branch_id")
                for item in branches
                if isinstance(item, Mapping) and isinstance(item.get("branch_id"), str)
            ]
    if decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE:
        graph_candidate = decision.payload.get("graph_candidate", {})
        if isinstance(graph_candidate, Mapping):
            metadata["selected_branch_id"] = graph_candidate.get("branch_id")
    if decision.decision_type is HarnessGraphDecisionType.START_LOOP_ITERATION:
        metadata["selected_loop_route_id"] = "continue"
    return metadata


def _merged_node_metadata(
    node: HarnessNodeInstanceState,
    decision: HarnessGraphDecision,
) -> dict[str, Any]:
    metadata = thaw_json(node.metadata)
    metadata.update(_decision_metadata(decision))
    return metadata


def _state_evidence_refs(state: HarnessGraphState) -> set[str]:
    refs = {
        canonical_checksum(item.to_dict()) for item in state.node_instances
    }
    for node in state.node_instances:
        refs.update(item.evidence_ref for item in node.evidence_refs)
    for join in state.join_states:
        refs.update(join.terminal_event_refs.values())
    for wait in state.wait_registrations:
        if wait.resolution_event_ref is not None:
            refs.add(wait.resolution_event_ref)
    for entry in state.compensation_stack:
        refs.add(entry.effect_outcome_ref)
        if entry.outcome_ref is not None:
            refs.add(entry.outcome_ref)
    if state.terminal_evidence_ref is not None:
        refs.add(state.terminal_evidence_ref)
    return refs


def _definition(
    graph: NormalizedHarnessGraph,
    node_id: str,
) -> HarnessGraphNode:
    definition = next((item for item in graph.nodes if item.node_id == node_id), None)
    if definition is None:
        raise HarnessValidationError(
            "graph node definition is missing",
            code="graph_control_decision_mismatch",
            details={"node_id": node_id},
        )
    return definition


def _executable_binding_versions(
    definition: HarnessExecutableNode,
) -> dict[str, str]:
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


def _node_instance(
    state: HarnessGraphState,
    node_instance_id: str,
) -> HarnessNodeInstanceState:
    node = next(
        (item for item in state.node_instances if item.instance_id == node_instance_id),
        None,
    )
    if node is None:
        raise HarnessValidationError(
            "graph node instance is missing",
            code="graph_control_decision_mismatch",
            details={"node_instance_id": node_instance_id},
        )
    return node


def _replace_node(
    nodes: tuple[HarnessNodeInstanceState, ...],
    updated: HarnessNodeInstanceState,
) -> tuple[HarnessNodeInstanceState, ...]:
    return tuple(updated if item.instance_id == updated.instance_id else item for item in nodes)


def _projection_for_cause(
    recovery: HarnessGraphRecovery,
    cause_checksum: str,
) -> HarnessGraphProjectionCommit | None:
    return next(
        (
            item
            for item in recovery.projection_commits
            if item.cause_checksum == cause_checksum
        ),
        None,
    )


def _run_spec_checksum_from_state(state: HarnessGraphState) -> str:
    value = state.metadata.get("run_spec_checksum")
    if not isinstance(value, str):
        raise EventIncompleteHistoryError(
            "graph state is missing its run spec checksum"
        )
    return value


def _freeze_counter_delta(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    frozen = freeze_json(value, field_name)
    if not isinstance(frozen, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_budget_delta",
        )
    return frozen


def _checksum_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(required_text(item, field_name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            f"{field_name} must not contain duplicates",
            code="duplicate_graph_control_evidence",
        )
    return normalized


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="invalid_graph_control_sequence",
        )
    return value


__all__ = [
    "HarnessGraphActivityDispatcherPort",
    "HarnessGraphAppliedDecision",
    "HarnessGraphControlPlaneRuntime",
    "HarnessGraphDecisionApplier",
]
