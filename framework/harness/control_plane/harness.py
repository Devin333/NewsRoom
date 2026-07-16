from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable, Iterable

from framework.events.canonical import PayloadReference, checksum_for
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
)
from framework.events.runtime.activities import ReplayActivityDescriptor
from framework.harness.control_plane.activity import (
    HarnessActivity,
    validate_activity_call_marker,
)
from framework.harness.control_plane.decision import HarnessDecision, HarnessDecisionType
from framework.harness.control_plane.durable_events import (
    HarnessRecovery,
    HarnessTransitionCommit,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.replay_history import (
    harness_decision_history,
    harness_decision_input_snapshot,
)
from framework.harness.control_plane.gates import (
    DeterministicGate,
    GateContext,
    HarnessGateResult,
    default_plan_gates,
    default_verify_gates,
)
from framework.harness.control_plane.phase import (
    HarnessPhase,
    HarnessPhaseBoundary,
    HarnessPhaseRecord,
)
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.control_plane.scheduler import HarnessScheduler
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
    HarnessStepState,
    HarnessStepStatus,
)
from framework.harness.control_plane.transitions import (
    get_step_state,
    replace_step_state,
    terminal_run_statuses,
    transition_run,
    transition_step,
)
from framework.harness.control_plane.transition import (
    HarnessStateProjection,
    HarnessTransitionCommitted,
    HarnessTransitionKind,
    run_spec_checksum,
)
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus

WorkerCallable = Callable[[dict[str, Any]], HarnessWorkerResult]

_ACTIVITY_RESULT_METADATA_KEYS = frozenset(
    {
        "activity_result_event_id",
        "worker_result_ref",
        "worker_status",
        "worker_result",
        "error_ref",
        "approval_granted",
    }
)

if TYPE_CHECKING:
    from framework.harness.ports import HarnessTransitionPort


@dataclass(frozen=True)
class HarnessRunResult:
    state: HarnessState
    decisions: tuple[HarnessDecision, ...]
    events: tuple[HarnessEvent, ...]
    worker_results: dict[str, HarnessWorkerResult]
    quality_verdicts: dict[str, HarnessQualityVerdict]

    @property
    def succeeded(self) -> bool:
        return self.state.status == HarnessRunStatus.SUCCEEDED


class InMemoryHarnessEventPort:
    """Explicit test-only sink; production composition must use a durable port."""

    def __init__(self) -> None:
        self.events: list[HarnessEvent] = []
        self.transitions: dict[str, list[HarnessTransitionCommitted]] = {}
        self.states: dict[str, HarnessState] = {}
        self.worker_results: dict[str, dict[str, HarnessWorkerResult]] = {}
        self.activity_results: dict[str, HarnessWorkerResult] = {}

    def record(self, event: HarnessEvent) -> HarnessEvent:
        self.events.append(event)
        return event

    def create_activity(
        self,
        *,
        run_id: str,
        step_id: str,
        attempt: int,
        activity_type: str,
        inputs: dict[str, Any],
        worker_version: str = "1",
    ) -> HarnessActivity:
        return HarnessActivity.for_worker_call(
            run_id=run_id,
            step_id=step_id,
            attempt=attempt,
            activity_type=activity_type,
            inputs=inputs,
            worker_version=worker_version,
        )

    def commit_transition(
        self,
        previous: HarnessState | None,
        state: HarnessState,
        *,
        from_version: int,
        transition_kind: HarnessTransitionKind | str,
        occurred_at,
        decision=None,
        gate_results=None,
        budget=None,
        activity: HarnessActivity | None = None,
        activity_result_event_id: str | None = None,
    ) -> HarnessTransitionCommit:
        run_id = state.run_spec.run_id
        history = self.transitions.setdefault(run_id, [])
        if from_version != len(history):
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness transition attempted from a stale state version",
            )
        if previous is None:
            if run_id in self.states:
                raise EventReplayMismatchError(
                    sequence=len(self.events),
                    reason="Harness initialization attempted after state already exists",
                )
        else:
            current = self.states.get(run_id)
            if current is None or (
                HarnessStateProjection.from_state(current).checksum
                != HarnessStateProjection.from_state(previous).checksum
            ):
                raise EventReplayMismatchError(
                    sequence=len(self.events),
                    reason="Harness in-memory projection does not match committed state",
                )
        transition = HarnessTransitionCommitted.create(
            previous=previous,
            state=state,
            from_version=from_version,
            expected_last_sequence=len(self.events),
            transition_kind=transition_kind,
            occurred_at=occurred_at,
            decision=decision,
            gate_results=gate_results,
            budget=budget,
            activity_result_event_id=activity_result_event_id,
            activity_id=None if activity is None else activity.activity_id,
            idempotency_key=None if activity is None else activity.idempotency_key,
        )
        history.append(transition)
        self.states[run_id] = state
        self.events.append(
            HarnessEvent(
                event_id=transition.transition_id,
                event_type=HarnessEventType.TRANSITION_COMMITTED,
                run_id=run_id,
                step_id=state.current_step_id,
                payload=transition.to_payload(),
                occurred_at=transition.occurred_at,
            )
        )
        return HarnessTransitionCommit(
            state=state,
            transition=transition,
            stored_event=None,
        )

    def recover(self, run_spec: HarnessRunSpec) -> HarnessRecovery:
        state = self.states.get(run_spec.run_id)
        if state is not None and run_spec_checksum(state.run_spec) != run_spec_checksum(run_spec):
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness run specification checksum mismatch",
            )
        results: dict[str, HarnessWorkerResult] = {}
        if state is not None:
            for step in state.step_states:
                activity = _activity_for_state_step(state, step.step_id)
                if activity is None:
                    continue
                result = self.activity_results.get(activity.activity_id)
                if result is not None:
                    results[step.step_id] = result
        transitions = tuple(self.transitions.get(run_spec.run_id, ()))
        return HarnessRecovery(
            state=state,
            state_version=len(transitions),
            expected_last_sequence=len(self.events),
            transitions=transitions,
            stored_events=(),
            worker_results=results,
            called_activity_ids=_in_memory_called_activity_ids(
                state=state,
                transitions=transitions,
                events=tuple(
                    event for event in self.events if event.run_id == run_spec.run_id
                ),
            ),
        )

    def read_history(self, run_id: str) -> tuple[HarnessEvent, ...]:
        return tuple(event for event in self.events if event.run_id == run_id)

    def require_activity_storage(self) -> None:
        return None

    def accept_activity(
        self,
        activity: HarnessActivity,
        inputs: dict[str, Any],
        *,
        accepted_at,
        started_at,
    ) -> HarnessWorkerResult | None:
        del inputs, accepted_at, started_at
        return self.activity_results.get(activity.activity_id)

    def resolve_replay_activity(
        self,
        state: HarnessState,
    ) -> tuple[ReplayActivityDescriptor, PayloadReference] | None:
        del state
        return None

    def record_activity_result(
        self,
        activity: HarnessActivity,
        result: HarnessWorkerResult,
        *,
        completed_at,
    ) -> HarnessEvent:
        results = self.worker_results.setdefault(activity.run_id, {})
        existing = self.activity_results.get(activity.activity_id)
        if existing is not None and existing.to_dict() != result.to_dict():
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness activity retry produced a different result",
            )
        self.activity_results[activity.activity_id] = result
        results[activity.step_id] = result
        projected = HarnessEvent(
            event_id=activity.result_event_id,
            event_type=HarnessEventType.WORKER_RESULT_RECORDED,
            run_id=activity.run_id,
            step_id=activity.step_id,
            payload={
                "projection_schema": "harness-safe-summary/v1",
                "status": result.status.value,
                "output_ref": checksum_for(result.to_dict()),
                "activity_id": activity.activity_id,
            },
            occurred_at=completed_at,
        )
        if not any(event.event_id == projected.event_id for event in self.events):
            self.events.append(projected)
        return projected


class HarnessControlPlane:
    def __init__(
        self,
        *,
        scheduler: HarnessScheduler | None = None,
        event_port: HarnessTransitionPort | None = None,
        worker_registry: dict[str, WorkerCallable | Iterable[HarnessWorkerResult]] | None = None,
        plan_gates: tuple[DeterministicGate, ...] | None = None,
        verify_gates: tuple[DeterministicGate, ...] | None = None,
    ) -> None:
        if event_port is None:
            raise HarnessValidationError(
                "Harness event_port is required; inject InMemoryHarnessEventPort explicitly only in tests"
            )
        if not _is_transition_port(event_port):
            raise HarnessValidationError(
                "Harness event_port must implement durable transition and recovery operations"
            )
        self.scheduler = scheduler or HarnessScheduler()
        self.event_port = event_port
        self.worker_registry = dict(worker_registry or {})
        self.plan_gates = plan_gates or default_plan_gates()
        self.verify_gates = verify_gates or default_verify_gates()
        self._iterable_workers: dict[str, list[HarnessWorkerResult]] = {}
        self._committed_events: list[HarnessEvent] = []
        self._state_versions: dict[str, int] = {}
        self._decision_indexes: dict[str, int] = {}
        self._recovered_worker_results: dict[str, HarnessWorkerResult] = {}
        self._recovered_gate_results: tuple[HarnessGateResult, ...] = ()
        self._recovered_quality_verdict: HarnessQualityVerdict | None = None

    def initialize(self, run_spec: HarnessRunSpec) -> HarnessState:
        recovery = self._restore_recovery(run_spec)
        if recovery.state is not None:
            return recovery.state
        state = HarnessState.initial(run_spec)
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id=run_spec.run_id,
                occurred_at=run_spec.created_at,
            )
        )
        return self._commit_transition(
            None,
            state,
            transition_kind=HarnessTransitionKind.INITIALIZE,
            occurred_at=run_spec.created_at,
        )

    def run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        state = self.initialize(run_spec)
        recovery = self._restore_recovery(run_spec)
        return self._drive(
            state,
            worker_result=recovery.current_worker_result,
            initial_gate_results=self._recovered_gate_results,
            initial_quality_verdict=self._recovered_quality_verdict,
        )

    def recover_and_run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        recovery = self._restore_recovery(run_spec)
        if recovery.state is None:
            raise EventIncompleteHistoryError(
                "Harness run has no committed recoverable state"
            )
        return self._drive(
            recovery.state,
            worker_result=recovery.current_worker_result,
            initial_gate_results=self._recovered_gate_results,
            initial_quality_verdict=self._recovered_quality_verdict,
        )

    def resume_after_approval(
        self,
        state: HarnessState | HarnessRunSpec,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> HarnessRunResult:
        """Durably resume or cancel one approval-waiting Harness projection."""

        if isinstance(state, HarnessRunSpec):
            supplied_state = None
            run_spec = state
        elif isinstance(state, HarnessState):
            supplied_state = state
            run_spec = state.run_spec
        else:
            raise TypeError("state must be HarnessState or HarnessRunSpec")
        recovery = self._restore_recovery(run_spec)
        if recovery.state is None:
            raise EventIncompleteHistoryError(
                "Harness approval resume requires committed recoverable state"
            )
        state = recovery.state
        if supplied_state is not None and (
            HarnessStateProjection.from_state(supplied_state).checksum
            != HarnessStateProjection.from_state(state).checksum
        ):
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="supplied Harness state does not match durable history",
            )
        if state.status != HarnessRunStatus.WAITING_APPROVAL:
            raise HarnessValidationError("Harness run is not waiting for approval")
        step_id = state.current_step_id
        if step_id is None:
            raise HarnessValidationError("approval-waiting Harness run requires current_step_id")
        if not approved:
            decision = HarnessDecision(
                decision_type=HarnessDecisionType.CANCEL_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason=reason or "Harness approval was cancelled",
                payload={"approval_outcome": "cancelled"},
            )
            replay_activity = _resolve_replay_activity_binding(
                self.event_port,
                state,
            )
            decision_input = self._decision_input(
                state,
                gate_results=(),
                quality_verdict=None,
                expected_activity=(
                    None if replay_activity is None else replay_activity[0]
                ),
                approval_outcome="cancelled",
            )
            self._record_decision(
                decision,
                decision_input=decision_input,
                replay_activity=replay_activity,
            )
            transition_time = _next_transition_time(state)
            cancelled = transition_step(
                state,
                step_id,
                HarnessStepStatus.HALTED,
                error=decision.reason,
                current_step_id=step_id,
                at=transition_time,
            )
            cancelled = transition_run(
                cancelled,
                HarnessRunStatus.CANCELLED,
                metadata={"terminal_reason": decision.reason},
                at=transition_time,
            )
            cancelled = self._commit_transition(
                state,
                cancelled,
                transition_kind=HarnessTransitionKind.APPROVAL_CANCEL,
                occurred_at=transition_time,
                decision=decision,
            )
            self._record_step_change(
                state,
                cancelled,
                step_id,
                transition_kind="approval_cancel",
            )
            self._record_state_change(
                state,
                cancelled,
                transition_kind="approval_cancel",
            )
            return self._result(cancelled, decisions=[decision])

        # Recovery may have only an integrity summary for the worker activity.
        # Prove the complete recorded result is available before committing any
        # approval-resume transition; otherwise fail closed at the old state.
        worker_result = recovery.current_worker_result
        if worker_result is None:
            raise EventIncompleteHistoryError(
                "approval resume requires a committed worker activity result"
            )
        decision = HarnessDecision(
            decision_type=HarnessDecisionType.RESUME_AFTER_APPROVAL,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason=reason or "Harness approval granted",
            payload={"approval_outcome": "approved"},
        )
        replay_activity = _resolve_replay_activity_binding(
            self.event_port,
            state,
        )
        decision_input = self._decision_input(
            state,
            gate_results=(),
            quality_verdict=None,
            expected_activity=(
                None if replay_activity is None else replay_activity[0]
            ),
            approval_outcome="approved",
        )
        self._record_decision(
            decision,
            decision_input=decision_input,
            replay_activity=replay_activity,
        )
        transition_time = _next_transition_time(state)
        resumed = transition_run(
            state,
            HarnessRunStatus.RUNNING,
            at=transition_time,
        )
        resumed = transition_step(
            resumed,
            step_id,
            HarnessStepStatus.RUNNING,
            metadata={"approval_granted": True},
            current_step_id=step_id,
            at=transition_time,
        )
        resumed = self._commit_transition(
            state,
            resumed,
            transition_kind=HarnessTransitionKind.APPROVAL_RESUME,
            occurred_at=transition_time,
            decision=decision,
        )
        self._record_state_change(
            state,
            resumed,
            transition_kind="approval_resume",
        )
        self._record_step_change(
            state,
            resumed,
            step_id,
            transition_kind="approval_resume",
        )
        return self._drive(
            resumed,
            initial_decisions=[decision],
            worker_result=worker_result,
        )

    def _drive(
        self,
        state: HarnessState,
        *,
        initial_decisions: list[HarnessDecision] | None = None,
        worker_result: HarnessWorkerResult | None = None,
        initial_gate_results: tuple[HarnessGateResult, ...] = (),
        initial_quality_verdict: HarnessQualityVerdict | None = None,
    ) -> HarnessRunResult:
        decisions: list[HarnessDecision] = list(initial_decisions or ())
        worker_results: dict[str, HarnessWorkerResult] = {}
        quality_verdicts: dict[str, HarnessQualityVerdict] = {}
        gate_results = initial_gate_results
        quality_verdict = initial_quality_verdict

        while state.status not in _run_loop_stop_statuses():
            replay_activity = _resolve_replay_activity_binding(
                self.event_port,
                state,
            )
            decision_input = self._decision_input(
                state,
                gate_results=gate_results,
                quality_verdict=quality_verdict,
                expected_activity=(
                    None if replay_activity is None else replay_activity[0]
                ),
            )
            decision = self.scheduler.next_decision(
                state,
                worker_result=worker_result,
                quality_verdict=quality_verdict,
                gate_results=gate_results,
            )
            self._record_decision(
                decision,
                decision_input=decision_input,
                replay_activity=replay_activity,
            )
            decisions.append(decision)

            if decision.decision_type == HarnessDecisionType.START_STEP:
                state = self._start_run(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.PLAN_STEP:
                state, gate_results = self._plan_step(state, decision)
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.EXECUTE_STEP:
                state, worker_result = self._execute_step(state, decision)
                worker_results[decision.step_id or ""] = worker_result
                gate_results = ()
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.VERIFY_STEP:
                state, gate_results, quality_verdict = self._verify_step(state, decision, worker_result)
                if quality_verdict is not None:
                    quality_verdicts[decision.step_id or ""] = quality_verdict
            elif decision.decision_type == HarnessDecisionType.COMPLETE_STEP:
                state = self._complete_step(state, decision, worker_result)
                gate_results = ()
            elif decision.decision_type == HarnessDecisionType.ROUTE_TO_STEP:
                state = self._route_to_step(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.ROUTE_TO_REPAIR:
                state = self._route_to_repair(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.RETRY_STEP:
                state = self._retry_step(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.REPLAN_STEP:
                state = self._replan_step(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.WAIT_FOR_APPROVAL:
                state = self._wait_for_approval(state, decision)
                gate_results = ()
            elif decision.decision_type == HarnessDecisionType.COMPLETE_RUN:
                state = self._finish_run(state, HarnessRunStatus.SUCCEEDED, decision)
            elif decision.decision_type == HarnessDecisionType.FAIL_RUN:
                state = self._finish_run(state, HarnessRunStatus.FAILED, decision)
            elif decision.decision_type == HarnessDecisionType.HALT_RUN:
                state = self._finish_run(state, HarnessRunStatus.HALTED, decision)
            elif decision.decision_type == HarnessDecisionType.BLOCK_RUN:
                state = self._finish_run(state, HarnessRunStatus.BLOCKED, decision)
            elif decision.decision_type == HarnessDecisionType.CANCEL_RUN:
                state = self._finish_run(state, HarnessRunStatus.CANCELLED, decision)
            else:
                state = self._finish_run(state, HarnessRunStatus.FAILED, decision)

        return self._result(
            state,
            decisions=decisions,
            worker_results=worker_results,
            quality_verdicts=quality_verdicts,
        )

    def _start_run(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        if state.status == HarnessRunStatus.CREATED:
            previous = state
            transition_time = _next_transition_time(state)
            candidate = transition_run(
                state,
                HarnessRunStatus.RUNNING,
                at=transition_time,
            )
            state = self._commit_transition(
                state,
                candidate,
                transition_kind=HarnessTransitionKind.RUN_START,
                occurred_at=transition_time,
                decision=decision,
            )
            self._record_state_change(
                previous,
                state,
                transition_kind="run_start",
            )
        return state

    def _plan_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
    ) -> tuple[HarnessState, tuple[HarnessGateResult, ...]]:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.RUNNING, HarnessRunStatus.REPLANNING}:
            state = transition_run(
                state,
                HarnessRunStatus.PLANNING,
                at=transition_time,
            )
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.PLANNING,
            turn_increment=1,
            current_step_id=step_id,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.PLAN_ENTRY,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="plan_entry")
        self._record_step_change(previous, state, step_id, transition_kind="plan_entry")
        self._record_phase(
            state,
            HarnessPhase.PLAN,
            step_id,
            (),
            boundary=HarnessPhaseBoundary.ENTRY,
        )
        gate_results = self._evaluate_gates(self.plan_gates, state, step_id, worker_result=None, quality_verdict=None)
        state = self._commit_plan_exit(
            state,
            step_id=step_id,
            gate_results=gate_results,
            record_observations=True,
        )
        return state, gate_results

    def _commit_plan_exit(
        self,
        state: HarnessState,
        *,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
        record_observations: bool,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        if all(result.passed for result in gate_results):
            state = transition_step(
                state,
                step_id,
                HarnessStepStatus.PLAN_VERIFIED,
                current_step_id=step_id,
                at=transition_time,
            )
        else:
            state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.PLAN_EXIT,
            occurred_at=transition_time,
            gate_results=gate_results,
        )
        if record_observations:
            self._record_phase(
                state,
                HarnessPhase.PLAN,
                step_id,
                gate_results,
                boundary=HarnessPhaseBoundary.EXIT,
            )
            if (
                get_step_state(previous, step_id).status
                != get_step_state(state, step_id).status
            ):
                self._record_step_change(
                    previous,
                    state,
                    step_id,
                    transition_kind="plan_exit",
                )
        return state

    def _execute_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
    ) -> tuple[HarnessState, HarnessWorkerResult]:
        step_id = _require_step(decision)
        self.event_port.require_activity_storage()
        step_spec = _get_step_spec(state, step_id)
        step_state = get_step_state(state, step_id)
        task = self._worker_task(step_spec, state)
        activity = self.event_port.create_activity(
            run_id=state.run_spec.run_id,
            step_id=step_id,
            attempt=step_state.attempts + 1,
            activity_type=step_spec.worker_type.value,
            inputs=task,
            worker_version=str(step_spec.metadata.get("worker_version", "1")),
        )
        activity_metadata = {
            "activity_id": activity.activity_id,
            "activity_type": activity.activity_type,
            "activity_contract_version": activity.contract_version,
            "activity_idempotency_key": activity.idempotency_key,
            "activity_input_checksum": activity.input_checksum,
            "activity_worker_version": activity.worker_version,
            "activity_attempt": activity.attempt,
        }
        if activity.identity_scope_ref is not None:
            activity_metadata["activity_identity_scope_ref"] = (
                activity.identity_scope_ref
            )
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.PLANNING, HarnessRunStatus.RUNNING, HarnessRunStatus.EXECUTING}:
            if state.status != HarnessRunStatus.EXECUTING:
                state = transition_run(
                    state,
                    HarnessRunStatus.EXECUTING,
                    at=transition_time,
                )
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.RUNNING,
            attempts=step_state.attempts + 1,
            turn_increment=1,
            worker_call_increment=1,
            metadata=activity_metadata,
            metadata_remove=_ACTIVITY_RESULT_METADATA_KEYS,
            clear_output_ref=True,
            current_step_id=step_id,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.EXECUTE_ENTRY,
            occurred_at=transition_time,
            decision=decision,
            activity=activity,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="execute_entry")
        self._record_step_change(previous, state, step_id, transition_kind="execute_entry")
        self._record_phase(state, HarnessPhase.EXECUTE, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)

        started_at = _next_transition_time(state)
        worker_result = self.event_port.accept_activity(
            activity,
            task,
            accepted_at=state.updated_at,
            started_at=started_at,
        )
        if worker_result is None:
            worker_result = self._call_worker(
                step_spec,
                state,
                task=task,
                activity=activity,
                started_at=started_at,
            )
        activity_result_event_id = self._record_activity_result(
            state,
            step_id=step_id,
            activity=activity,
            worker_result=worker_result,
        )
        state = self._commit_worker_result_transitions(
            state,
            step_id=step_id,
            step_spec=step_spec,
            worker_result=worker_result,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
            decision=None,
        )
        return state, worker_result

    def _record_activity_result(
        self,
        state: HarnessState,
        *,
        step_id: str,
        activity: HarnessActivity,
        worker_result: HarnessWorkerResult,
    ) -> str:
        activity_result_event = self.event_port.record_activity_result(
            activity,
            worker_result,
            completed_at=_next_transition_time(state),
        )
        if not isinstance(activity_result_event, HarnessEvent):
            raise HarnessValidationError(
                "Harness transition port returned an invalid activity result projection"
            )
        if (
            activity_result_event.event_id != activity.result_event_id
            or activity_result_event.event_type
            != HarnessEventType.WORKER_RESULT_RECORDED
            or activity_result_event.run_id != state.run_spec.run_id
            or activity_result_event.step_id != step_id
        ):
            raise HarnessValidationError(
                "Harness transition port returned a conflicting activity result projection"
            )
        if not any(
            event.event_id == activity_result_event.event_id
            for event in self._committed_events
        ):
            self._committed_events.append(activity_result_event)
        return str(activity_result_event.event_id)

    def _commit_worker_result_transitions(
        self,
        state: HarnessState,
        *,
        step_id: str,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult,
        activity: HarnessActivity,
        activity_result_event_id: str,
        decision: HarnessDecision | None,
    ) -> HarnessState:
        state = self._commit_worker_result_transition(
            state,
            step_id=step_id,
            step_spec=step_spec,
            worker_result=worker_result,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
            decision=decision,
        )
        return self._commit_execute_exit_transition(
            state,
            step_id=step_id,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
            decision=decision,
        )

    def _commit_worker_result_transition(
        self,
        state: HarnessState,
        *,
        step_id: str,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult,
        activity: HarnessActivity,
        activity_result_event_id: str,
        decision: HarnessDecision | None,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace_step_state(
            state,
            replace(
                get_step_state(state, step_id),
                output_ref=step_spec.output_key if worker_result.status == HarnessWorkerStatus.SUCCEEDED else None,
                error=worker_result.error,
                metadata={
                    **get_step_state(state, step_id).metadata,
                    "activity_result_event_id": activity_result_event_id,
                    "worker_result_ref": checksum_for(worker_result.to_dict()),
                    "worker_status": worker_result.status.value,
                    "worker_result": worker_result.to_dict(),
                },
                updated_at=transition_time,
            ),
            current_step_id=step_id,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.WORKER_RESULT_COMMITTED,
            occurred_at=transition_time,
            decision=decision,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
        )
        return state

    def _commit_execute_exit_transition(
        self,
        state: HarnessState,
        *,
        step_id: str,
        activity: HarnessActivity,
        activity_result_event_id: str,
        decision: HarnessDecision | None,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.EXECUTE_EXIT,
            occurred_at=transition_time,
            decision=decision,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
        )
        self._record_phase(
            state,
            HarnessPhase.EXECUTE,
            step_id,
            (),
            boundary=HarnessPhaseBoundary.EXIT,
        )
        return state

    def _verify_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        worker_result: HarnessWorkerResult | None,
    ) -> tuple[HarnessState, tuple[HarnessGateResult, ...], HarnessQualityVerdict | None]:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.RUNNING}:
            state = transition_run(
                state,
                HarnessRunStatus.VERIFYING,
                at=transition_time,
            )
        step_state = get_step_state(state, step_id)
        if step_state.status == HarnessStepStatus.RUNNING:
            state = transition_step(
                state,
                step_id,
                HarnessStepStatus.VERIFYING,
                current_step_id=step_id,
                turn_increment=1,
                at=transition_time,
            )
        else:
            state = replace_step_state(
                state,
                step_state,
                current_step_id=step_id,
                turn_increment=1,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.VERIFY_ENTRY,
            occurred_at=transition_time,
            decision=decision,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="verify_entry")
        self._record_step_change(previous, state, step_id, transition_kind="verify_entry")
        self._record_phase(state, HarnessPhase.VERIFY, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)
        quality_verdict = self._quality_verdict(state, step_id, worker_result)
        gate_results = self._evaluate_gates(
            self.verify_gates,
            state,
            step_id,
            worker_result=worker_result,
            quality_verdict=quality_verdict,
        )
        state = self._commit_verify_exit(
            state,
            step_id=step_id,
            gate_results=gate_results,
            record_observations=True,
        )
        return state, gate_results, quality_verdict

    def _commit_verify_exit(
        self,
        state: HarnessState,
        *,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
        record_observations: bool,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.VERIFY_EXIT,
            occurred_at=transition_time,
            gate_results=gate_results,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        if record_observations:
            self._record_phase(
                state,
                HarnessPhase.VERIFY,
                step_id,
                gate_results,
                boundary=HarnessPhaseBoundary.EXIT,
            )
        return state

    def _complete_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.SUCCEEDED,
            metadata={"worker_result": worker_result.to_dict() if worker_result is not None else None},
            current_step_id=step_id,
            at=transition_time,
        )
        state = _merge_outputs(state, step_id, worker_result)
        if state.status == HarnessRunStatus.VERIFYING:
            state = transition_run(
                state,
                HarnessRunStatus.RUNNING,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.STEP_SUCCESS,
            occurred_at=transition_time,
            decision=decision,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        self._record_step_change(previous, state, step_id, transition_kind="step_success")
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="verify_complete")
        return state

    def _route_to_step(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        target_step_id = decision.target_step_id or state.run_spec.workflow.entry_step_id
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = transition_run(
                state,
                HarnessRunStatus.RUNNING,
                at=transition_time,
            )
        step_state = get_step_state(state, target_step_id)
        if step_state.status == HarnessStepStatus.PENDING:
            state = replace(
                state,
                current_step_id=target_step_id,
                updated_at=transition_time,
            )
        else:
            reset_step = replace(
                step_state,
                status=HarnessStepStatus.PENDING,
                error=None,
                metadata={**step_state.metadata, "rerouted": True},
                updated_at=transition_time,
            )
            state = replace_step_state(
                state,
                reset_step,
                current_step_id=target_step_id,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.ROUTE_TO_STEP,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="route_to_step")
        if get_step_state(previous, target_step_id) != get_step_state(state, target_step_id):
            self._record_step_change(
                previous,
                state,
                target_step_id,
                transition_kind="route_to_step",
            )
        return state

    def _route_to_repair(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        if decision.step_id:
            candidate = _fail_current_step(
                state,
                decision.step_id,
                decision.reason,
                at=transition_time,
            )
            if candidate is not state:
                state = candidate
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = transition_run(state, HarnessRunStatus.RUNNING, at=transition_time)
        target_step_id = decision.target_step_id or state.run_spec.workflow.entry_step_id
        target = get_step_state(state, target_step_id)
        if target.status != HarnessStepStatus.PENDING:
            target = replace(
                target,
                status=HarnessStepStatus.PENDING,
                error=None,
                metadata={**target.metadata, "rerouted": True},
                updated_at=transition_time,
            )
            state = replace_step_state(
                state,
                target,
                current_step_id=target_step_id,
                at=transition_time,
            )
        else:
            state = replace(
                state,
                current_step_id=target_step_id,
                updated_at=transition_time,
            )
        state = replace(
            state,
            metadata={**state.metadata, "repair_from_step_id": decision.step_id},
            updated_at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.ROUTE_TO_REPAIR,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="route_to_repair")
        if decision.step_id and get_step_state(previous, decision.step_id) != get_step_state(state, decision.step_id):
            self._record_step_change(
                previous,
                state,
                decision.step_id,
                transition_kind="route_to_repair",
            )
        if get_step_state(previous, target_step_id) != get_step_state(state, target_step_id):
            self._record_step_change(
                previous,
                state,
                target_step_id,
                transition_kind="route_to_repair",
            )
        return state

    def _retry_step(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.RETRYING,
            current_step_id=step_id,
            error=decision.reason,
            at=transition_time,
        )
        if state.status != HarnessRunStatus.EXECUTING:
            state = transition_run(
                state,
                HarnessRunStatus.EXECUTING,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.RETRY,
            occurred_at=transition_time,
            decision=decision,
        )
        self._record_step_change(previous, state, step_id, transition_kind="retry")
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="retry")
        return state

    def _replan_step(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.PLANNING, HarnessRunStatus.VERIFYING}:
            state = transition_run(
                state,
                HarnessRunStatus.REPLANNING,
                at=transition_time,
            )
        step_state = get_step_state(state, step_id)
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.REPLANNING,
            replans=step_state.replans + 1,
            replan_increment=1,
            current_step_id=step_id,
            error=decision.reason,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.REPLAN_ENTRY,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="replan")
        self._record_step_change(previous, state, step_id, transition_kind="replan")
        self._record_phase(state, HarnessPhase.REPLAN, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)
        return self._commit_replan_exit(
            state,
            step_id=step_id,
            record_observations=True,
        )

    def _commit_replan_exit(
        self,
        state: HarnessState,
        *,
        step_id: str,
        record_observations: bool,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.REPLAN_EXIT,
            occurred_at=transition_time,
        )
        if record_observations:
            self._record_phase(
                state,
                HarnessPhase.REPLAN,
                step_id,
                (),
                boundary=HarnessPhaseBoundary.EXIT,
            )
        return state

    def _wait_for_approval(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.RUNNING, HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = transition_run(
                state,
                HarnessRunStatus.WAITING_APPROVAL,
                at=transition_time,
            )
        step_state = get_step_state(state, step_id)
        if step_state.status != HarnessStepStatus.WAITING_APPROVAL:
            state = transition_step(
                state,
                step_id,
                HarnessStepStatus.WAITING_APPROVAL,
                error=decision.reason,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.WAIT_FOR_APPROVAL,
            occurred_at=transition_time,
            decision=decision,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="wait_for_approval")
        if get_step_state(previous, step_id).status != get_step_state(state, step_id).status:
            self._record_step_change(
                previous,
                state,
                step_id,
                transition_kind="wait_for_approval",
            )
        return state

    def _finish_run(self, state: HarnessState, status: HarnessRunStatus, decision: HarnessDecision) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        if status == HarnessRunStatus.HALTED and decision.step_id:
            self._record_phase(
                state,
                HarnessPhase.HALT,
                decision.step_id,
                (),
                boundary=HarnessPhaseBoundary.ENTRY,
            )
            candidate = _halt_current_step(
                state,
                decision.step_id,
                decision.reason,
                at=transition_time,
            )
            if candidate is not state:
                state = candidate
        if status == HarnessRunStatus.FAILED and decision.step_id:
            candidate = _fail_current_step(
                state,
                decision.step_id,
                decision.reason,
                at=transition_time,
            )
            if candidate is not state:
                state = candidate
        state = transition_run(
            state,
            status,
            metadata={"terminal_reason": decision.reason},
            at=transition_time,
        )
        transition_kind = _terminal_transition_kind(status, decision)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=transition_kind,
            occurred_at=transition_time,
            decision=decision,
            activity=(
                None
                if decision.step_id is None
                else _activity_for_state_step(state, decision.step_id)
            ),
            activity_result_event_id=(
                None
                if decision.step_id is None
                else _activity_result_event_id(state, decision.step_id)
            ),
        )
        if decision.step_id and get_step_state(previous, decision.step_id) != get_step_state(state, decision.step_id):
            self._record_step_change(
                previous,
                state,
                decision.step_id,
                transition_kind=transition_kind.value,
            )
        self._record_state_change(
            previous,
            state,
            transition_kind=transition_kind.value,
        )
        if status == HarnessRunStatus.HALTED and decision.step_id:
            self._record_phase(
                state,
                HarnessPhase.HALT,
                decision.step_id,
                (),
                boundary=HarnessPhaseBoundary.EXIT,
            )
        return state

    def _evaluate_gates(
        self,
        gates: tuple[DeterministicGate, ...],
        state: HarnessState,
        step_id: str,
        *,
        worker_result: HarnessWorkerResult | None,
        quality_verdict: HarnessQualityVerdict | None,
        record_events: bool = True,
    ) -> tuple[HarnessGateResult, ...]:
        step_spec = _get_step_spec(state, step_id)
        context = GateContext(
            state=state,
            step_spec=step_spec,
            step_state=get_step_state(state, step_id),
            worker_result=worker_result,
            quality_verdict=quality_verdict,
            budget=self._budget_snapshot(state, worker_result),
        )
        results = tuple(gate.evaluate(context) for gate in gates)
        if record_events:
            for result in results:
                self._record_event(
                    HarnessEvent(
                        event_type=HarnessEventType.GATE_EVALUATED,
                        run_id=state.run_spec.run_id,
                        step_id=step_id,
                        payload=result.to_dict(),
                    )
                )
        return results

    def _budget_snapshot(
        self,
        state: HarnessState,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessBudgetSnapshot:
        output = worker_result.output if worker_result is not None else {}
        return HarnessBudgetSnapshot.from_budget(
            state.run_spec.budget,
            turns_used=state.turn_count,
            replans_used=state.replan_count,
            worker_calls_used=state.worker_call_count,
            evolution_epochs_used=int(state.metadata.get("evolution_epochs_used", 0)),
            candidates_used=int(state.metadata.get("candidates_used", 0)),
            patch_operations_used=int(state.metadata.get("patch_operations_used", 0)),
            eval_cases_used=int(state.metadata.get("eval_cases_used", 0)),
            sandbox_runs_used=int(state.metadata.get("sandbox_runs_used", 0)),
        )

    def _worker_task(
        self,
        step_spec: HarnessStepSpec,
        state: HarnessState,
    ) -> dict[str, Any]:
        outputs = state.metadata.get("outputs", {})
        prior_outputs = outputs if isinstance(outputs, dict) else {}
        return {
            "run_id": state.run_spec.run_id,
            "step_id": step_spec.step_id,
            "worker_type": step_spec.worker_type.value,
            "inputs": {
                key: prior_outputs[key] if key in prior_outputs else state.run_spec.inputs.get(key)
                for key in step_spec.input_keys
            },
            "metadata": step_spec.metadata,
        }

    def _call_worker(
        self,
        step_spec: HarnessStepSpec,
        state: HarnessState,
        *,
        task: dict[str, Any] | None = None,
        activity: HarnessActivity | None = None,
        started_at=None,
    ) -> HarnessWorkerResult:
        worker = self.worker_registry.get(step_spec.step_id) or self.worker_registry.get(step_spec.worker_type.value)
        task = dict(task or self._worker_task(step_spec, state))
        call_payload = dict(task)
        started_at = started_at or _next_transition_time(state)
        if activity is not None:
            call_payload.update(
                {
                    "activity_id": activity.activity_id,
                    "idempotency_key": activity.idempotency_key,
                    "activity_attempt": activity.attempt,
                    "activity_contract_version": activity.contract_version,
                }
            )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.WORKER_CALLED,
                run_id=state.run_spec.run_id,
                step_id=step_spec.step_id,
                payload=call_payload,
                occurred_at=started_at,
            )
        )
        execution_task = _task_with_activity(task, activity)
        if worker is None:
            return HarnessWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={},
            )
        if callable(worker):
            return worker(execution_task)
        execute = getattr(worker, "execute", None)
        if callable(execute):
            return execute(execution_task)
        if step_spec.worker_type.value == "llm":
            generate = getattr(worker, "generate", None)
            if callable(generate):
                return generate(execution_task)
        if step_spec.worker_type.value == "skill":
            run_skill = getattr(worker, "run_skill", None)
            if callable(run_skill):
                return run_skill(str(execution_task.get("skill_name", execution_task["step_id"])), dict(execution_task.get("inputs", {})), dict(execution_task.get("context", {})))
        if step_spec.worker_type.value == "subagent":
            run_subagent = getattr(worker, "run_subagent", None)
            if callable(run_subagent):
                return run_subagent(str(execution_task.get("subagent_id", execution_task["step_id"])), dict(execution_task), dict(execution_task.get("budget", {})))
        try:
            queued = self._iterable_workers.setdefault(step_spec.step_id, list(worker))
        except TypeError as exc:
            raise HarnessValidationError("worker registry value must be callable, a Harness worker port, or result iterable") from exc
        if not queued:
            return HarnessWorkerResult(
                status=HarnessWorkerStatus.FAILED,
                error="fake worker queue is exhausted",
            )
        return queued.pop(0)

    def _quality_verdict(
        self,
        state: HarnessState,
        step_id: str,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessQualityVerdict | None:
        if worker_result is None:
            return None
        step_spec = _get_step_spec(state, step_id)
        verdict = step_spec.metadata.get("quality_verdict")
        if isinstance(verdict, HarnessQualityVerdict):
            return verdict
        if isinstance(verdict, dict):
            return HarnessQualityVerdict(**verdict)
        if "quality_score" in worker_result.output:
            score = float(worker_result.output["quality_score"])
            return HarnessQualityVerdict(passed=score >= float(step_spec.metadata.get("minimum_quality_score", 0)), score=score)
        return HarnessQualityVerdict(passed=True)

    def _record_decision(
        self,
        decision: HarnessDecision,
        *,
        decision_input: Mapping[str, Any],
        replay_activity: tuple[
            ReplayActivityDescriptor,
            PayloadReference,
        ]
        | None = None,
    ) -> None:
        ordinal = self._decision_indexes.get(decision.run_id, 0)
        history = harness_decision_history(
            workflow_id=str(decision_input["workflow_id"]),
            workflow_version=str(decision_input["workflow_version"]),
            command_ordinal=ordinal,
            decision_input=decision_input,
            decision=decision,
            causation_id=str(decision_input["causation_id"]),
            expected_activity=(
                None if replay_activity is None else replay_activity[0]
            ),
            recorded_activity_ref=(
                None if replay_activity is None else replay_activity[1]
            ),
        )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.DECISION_RECORDED,
                run_id=decision.run_id,
                step_id=decision.step_id,
                payload=decision.to_dict(),
                occurred_at=decision.decided_at,
                deterministic_history=history.to_dict(),
            )
        )
        self._decision_indexes[decision.run_id] = ordinal + 1

    def _decision_input(
        self,
        state: HarnessState,
        *,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
        expected_activity: ReplayActivityDescriptor | None,
        approval_outcome: str | None = None,
    ) -> Mapping[str, Any]:
        run_id = state.run_spec.run_id
        ordinal = self._decision_indexes.get(run_id, 0)
        causation_id = (
            self._committed_events[-1].event_id
            if self._committed_events
            else f"harness-run:{run_id}"
        )
        return harness_decision_input_snapshot(
            state=state,
            command_ordinal=ordinal,
            causation_id=str(causation_id),
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            expected_activity=expected_activity,
            approval_outcome=approval_outcome,
        )

    def _record_phase(
        self,
        state: HarnessState,
        phase: HarnessPhase,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
        *,
        boundary: HarnessPhaseBoundary,
    ) -> None:
        record = HarnessPhaseRecord(
            phase=phase,
            step_id=step_id,
            boundary=boundary,
            gate_results=tuple(result.to_dict() for result in gate_results),
            metadata={"turn_count": state.turn_count, "worker_call_count": state.worker_call_count},
        )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                payload=record.to_dict(),
                occurred_at=record.occurred_at,
            )
        )

    def _record_state_change(
        self,
        previous: HarnessState,
        state: HarnessState,
        *,
        transition_kind: str,
    ) -> None:
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.RUN_STATE_CHANGED,
                run_id=state.run_spec.run_id,
                step_id=state.current_step_id,
                payload={"status": state.status.value},
                metadata={
                    "replan_count": state.replan_count,
                    "status_before": previous.status.value,
                    "status_after": state.status.value,
                    "transition_kind": transition_kind,
                    "turn_count": state.turn_count,
                    "worker_call_count": state.worker_call_count,
                },
                occurred_at=state.updated_at,
            )
        )

    def _record_step_change(
        self,
        previous: HarnessState,
        state: HarnessState,
        step_id: str,
        *,
        transition_kind: str,
    ) -> None:
        previous_step = get_step_state(previous, step_id)
        current_step = get_step_state(state, step_id)
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.STEP_STATE_CHANGED,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                payload=current_step.to_dict(),
                metadata={
                    "replan_count": state.replan_count,
                    "status_before": previous_step.status.value,
                    "status_after": current_step.status.value,
                    "transition_kind": transition_kind,
                    "turn_count": state.turn_count,
                    "worker_call_count": state.worker_call_count,
                },
                occurred_at=current_step.updated_at,
            )
        )

    def _record_event(self, event: HarnessEvent) -> HarnessEvent:
        committed = self.event_port.record(event)
        if not isinstance(committed, HarnessEvent):
            raise HarnessValidationError(
                "Harness event_port must return the authoritative committed HarnessEvent projection"
            )
        if (
            committed.run_id != event.run_id
            or committed.step_id != event.step_id
            or committed.event_type != event.event_type
        ):
            raise HarnessValidationError("Harness event_port returned a conflicting committed projection")
        self._committed_events.append(committed)
        return committed

    def _restore_recovery(self, run_spec: HarnessRunSpec) -> HarnessRecovery:
        self._recovered_gate_results = ()
        self._recovered_quality_verdict = None
        converged_exit_kind: HarnessTransitionKind | None = None
        converged_gate_results: tuple[HarnessGateResult, ...] = ()
        converged_quality_verdict: HarnessQualityVerdict | None = None
        while True:
            recovery = self.event_port.recover(run_spec)
            if not isinstance(recovery, HarnessRecovery):
                raise HarnessValidationError(
                    "Harness transition port returned an invalid recovery result"
                )
            self._state_versions[run_spec.run_id] = recovery.state_version
            self._recovered_worker_results = dict(recovery.worker_results)
            state = recovery.state
            if state is None or not recovery.transitions:
                break
            last_transition = recovery.transitions[-1]
            transition_kind = last_transition.transition_kind
            step_id = state.current_step_id

            if transition_kind == HarnessTransitionKind.EXECUTE_ENTRY:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness execute recovery requires a current step"
                    )
                activity = _activity_for_state_step(state, step_id)
                if activity is None:
                    raise EventIncompleteHistoryError(
                        "Harness recovery is missing the worker activity descriptor"
                    )
                step_spec = _get_step_spec(state, step_id)
                worker_result = recovery.current_worker_result
                if worker_result is None:
                    task = self._worker_task(step_spec, state)
                    if checksum_for(task) != activity.input_checksum:
                        raise EventReplayMismatchError(
                            sequence=last_transition.stream_sequence
                            or last_transition.state_version,
                            reason=(
                                "Harness recovered activity input conflicts with "
                                "the committed activity descriptor"
                            ),
                        )
                    started_at = _next_transition_time(state)
                    worker_result = self.event_port.accept_activity(
                        activity,
                        task,
                        accepted_at=state.updated_at,
                        started_at=started_at,
                    )
                    if worker_result is None:
                        if activity.activity_id in recovery.called_activity_ids:
                            raise EventIncompleteHistoryError(
                                "Harness activity was dispatched without a durable result; "
                                "automatic worker re-execution is forbidden without "
                                "a verified idempotency capability"
                            )
                        worker_result = self._call_worker(
                            step_spec,
                            state,
                            task=task,
                            activity=activity,
                            started_at=started_at,
                        )
                    activity_result_event_id = self._record_activity_result(
                        state,
                        step_id=step_id,
                        activity=activity,
                        worker_result=worker_result,
                    )
                else:
                    activity_result_event_id = activity.result_event_id
                state = self._commit_worker_result_transition(
                    state,
                    step_id=step_id,
                    step_spec=step_spec,
                    worker_result=worker_result,
                    activity=activity,
                    activity_result_event_id=activity_result_event_id,
                    decision=None,
                )
                self._commit_execute_exit_transition(
                    state,
                    step_id=step_id,
                    activity=activity,
                    activity_result_event_id=activity_result_event_id,
                    decision=None,
                )
                continue

            if transition_kind == HarnessTransitionKind.WORKER_RESULT_COMMITTED:
                if step_id is None or recovery.current_worker_result is None:
                    raise EventIncompleteHistoryError(
                        "Harness execute recovery is missing its committed worker result"
                    )
                activity = _activity_for_state_step(state, step_id)
                activity_result_event_id = _activity_result_event_id(state, step_id)
                if activity is None or activity_result_event_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness execute recovery is missing its activity references"
                    )
                self._commit_execute_exit_transition(
                    state,
                    step_id=step_id,
                    activity=activity,
                    activity_result_event_id=activity_result_event_id,
                    decision=None,
                )
                continue

            if transition_kind == HarnessTransitionKind.PLAN_ENTRY:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness plan recovery requires a current step"
                    )
                gate_results = self._evaluate_gates(
                    self.plan_gates,
                    state,
                    step_id,
                    worker_result=None,
                    quality_verdict=None,
                    record_events=False,
                )
                self._commit_plan_exit(
                    state,
                    step_id=step_id,
                    gate_results=gate_results,
                    record_observations=False,
                )
                converged_exit_kind = HarnessTransitionKind.PLAN_EXIT
                converged_gate_results = gate_results
                continue

            if transition_kind == HarnessTransitionKind.VERIFY_ENTRY:
                worker_result = recovery.current_worker_result
                if step_id is None or worker_result is None:
                    raise EventIncompleteHistoryError(
                        "Harness verify recovery requires a committed worker result"
                    )
                quality_verdict = self._quality_verdict(
                    state,
                    step_id,
                    worker_result,
                )
                gate_results = self._evaluate_gates(
                    self.verify_gates,
                    state,
                    step_id,
                    worker_result=worker_result,
                    quality_verdict=quality_verdict,
                    record_events=False,
                )
                self._commit_verify_exit(
                    state,
                    step_id=step_id,
                    gate_results=gate_results,
                    record_observations=False,
                )
                converged_exit_kind = HarnessTransitionKind.VERIFY_EXIT
                converged_gate_results = gate_results
                converged_quality_verdict = quality_verdict
                continue

            if transition_kind == HarnessTransitionKind.REPLAN_ENTRY:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness replan recovery requires a current step"
                    )
                self._commit_replan_exit(
                    state,
                    step_id=step_id,
                    record_observations=False,
                )
                continue
            break

        if recovery.state is not None and recovery.transitions:
            state = recovery.state
            last_transition = recovery.transitions[-1]
            step_id = state.current_step_id
            if last_transition.transition_kind == HarnessTransitionKind.PLAN_EXIT:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness plan recovery requires a current step"
                    )
                if converged_exit_kind == HarnessTransitionKind.PLAN_EXIT:
                    gate_results = converged_gate_results
                else:
                    evaluation_state = _phase_entry_evaluation_state(
                        recovery,
                        expected_entry=HarnessTransitionKind.PLAN_ENTRY,
                    )
                    gate_results = self._evaluate_gates(
                        self.plan_gates,
                        evaluation_state,
                        step_id,
                        worker_result=None,
                        quality_verdict=None,
                        record_events=False,
                    )
                _validate_recovered_gate_results(last_transition, gate_results)
                self._recovered_gate_results = gate_results
            elif last_transition.transition_kind == HarnessTransitionKind.VERIFY_EXIT:
                worker_result = recovery.current_worker_result
                if step_id is None or worker_result is None:
                    raise EventIncompleteHistoryError(
                        "Harness verify recovery requires a committed worker result"
                    )
                if converged_exit_kind == HarnessTransitionKind.VERIFY_EXIT:
                    gate_results = converged_gate_results
                    quality_verdict = converged_quality_verdict
                else:
                    evaluation_state = _phase_entry_evaluation_state(
                        recovery,
                        expected_entry=HarnessTransitionKind.VERIFY_ENTRY,
                    )
                    quality_verdict = self._quality_verdict(
                        evaluation_state,
                        step_id,
                        worker_result,
                    )
                    gate_results = self._evaluate_gates(
                        self.verify_gates,
                        evaluation_state,
                        step_id,
                        worker_result=worker_result,
                        quality_verdict=quality_verdict,
                        record_events=False,
                    )
                _validate_recovered_gate_results(last_transition, gate_results)
                self._recovered_gate_results = gate_results
                self._recovered_quality_verdict = quality_verdict
            elif last_transition.transition_kind == HarnessTransitionKind.STEP_SUCCESS:
                if step_id is not None and recovery.current_worker_result is not None:
                    self._recovered_quality_verdict = self._quality_verdict(
                        state,
                        step_id,
                        recovery.current_worker_result,
                    )
        history = self.event_port.read_history(run_spec.run_id)
        if not isinstance(history, tuple) or not all(
            isinstance(event, HarnessEvent) for event in history
        ):
            raise HarnessValidationError(
                "Harness transition port returned an invalid history projection"
            )
        self._committed_events = list(history)
        self._decision_indexes[run_spec.run_id] = sum(
            1
            for event in history
            if event.event_type == HarnessEventType.DECISION_RECORDED
        )
        return recovery

    def _commit_transition(
        self,
        previous: HarnessState | None,
        state: HarnessState,
        *,
        transition_kind: HarnessTransitionKind | str,
        occurred_at=None,
        decision: HarnessDecision | None = None,
        gate_results: tuple[HarnessGateResult, ...] = (),
        activity: HarnessActivity | None = None,
        activity_result_event_id: str | None = None,
    ) -> HarnessState:
        run_id = state.run_spec.run_id
        from_version = self._state_versions.get(run_id, 0)
        transition_time = occurred_at or state.updated_at
        commit = self.event_port.commit_transition(
            previous,
            state,
            from_version=from_version,
            transition_kind=transition_kind,
            occurred_at=transition_time,
            decision=(
                None if decision is None else _decision_transition_projection(decision)
            ),
            gate_results=tuple(result.to_dict() for result in gate_results),
            budget=self._budget_snapshot(state, None).to_dict(),
            activity=activity,
            activity_result_event_id=activity_result_event_id,
        )
        if not isinstance(commit, HarnessTransitionCommit):
            raise HarnessValidationError(
                "Harness transition port returned an invalid commit result"
            )
        if commit.transition.from_version != from_version:
            raise HarnessValidationError(
                "Harness transition port returned a conflicting state version"
            )
        self._state_versions[run_id] = commit.transition.state_version
        projected = HarnessEvent(
            event_id=commit.transition.transition_id,
            event_type=HarnessEventType.TRANSITION_COMMITTED,
            run_id=run_id,
            step_id=state.current_step_id,
            payload=commit.transition.to_payload(),
            occurred_at=commit.transition.occurred_at,
        )
        if not any(
            event.event_id == projected.event_id for event in self._committed_events
        ):
            self._committed_events.append(projected)
        return commit.state

    def _result(
        self,
        state: HarnessState,
        *,
        decisions: list[HarnessDecision],
        worker_results: dict[str, HarnessWorkerResult] | None = None,
        quality_verdicts: dict[str, HarnessQualityVerdict] | None = None,
    ) -> HarnessRunResult:
        run_id = state.run_spec.run_id
        all_worker_results = {
            **self._recovered_worker_results,
            **(worker_results or {}),
        }
        return HarnessRunResult(
            state=state,
            decisions=tuple(decisions),
            events=tuple(event for event in self._committed_events if event.run_id == run_id),
            worker_results={
                key: value
                for key, value in all_worker_results.items()
                if key
            },
            quality_verdicts={
                key: value
                for key, value in (quality_verdicts or {}).items()
                if key
            },
        )


def _require_step(decision: HarnessDecision) -> str:
    if decision.step_id:
        return decision.step_id
    if decision.target_step_id:
        return decision.target_step_id
    raise ValueError("decision requires a step_id")


def _is_transition_port(value: Any) -> bool:
    return all(
        callable(getattr(value, method_name, None))
        for method_name in (
            "record",
            "create_activity",
            "commit_transition",
            "recover",
            "read_history",
            "require_activity_storage",
            "accept_activity",
            "resolve_replay_activity",
            "record_activity_result",
        )
    )


def _resolve_replay_activity_binding(
    event_port: Any,
    state: HarnessState,
) -> tuple[ReplayActivityDescriptor, PayloadReference] | None:
    binding = event_port.resolve_replay_activity(state)
    if binding is None:
        return None
    if (
        not isinstance(binding, tuple)
        or len(binding) != 2
        or not isinstance(binding[0], ReplayActivityDescriptor)
        or not isinstance(binding[1], PayloadReference)
    ):
        raise HarnessValidationError(
            "Harness transition port returned an invalid replay activity binding"
        )
    return binding


def _get_step_spec(state: HarnessState, step_id: str) -> HarnessStepSpec:
    for step in state.run_spec.workflow.steps:
        if step.step_id == step_id:
            return step
    raise LookupError(step_id)


def _halt_current_step(
    state: HarnessState,
    step_id: str,
    reason: str | None,
    *,
    at,
) -> HarnessState:
    step_state = get_step_state(state, step_id)
    if step_state.status == HarnessStepStatus.HALTED:
        return state
    if step_state.status in {HarnessStepStatus.SUCCEEDED, HarnessStepStatus.FAILED, HarnessStepStatus.SKIPPED}:
        return state
    return transition_step(
        state,
        step_id,
        HarnessStepStatus.HALTED,
        error=reason,
        current_step_id=step_id,
        at=at,
    )


def _fail_current_step(
    state: HarnessState,
    step_id: str,
    reason: str | None,
    *,
    at,
) -> HarnessState:
    step_state = get_step_state(state, step_id)
    if step_state.status == HarnessStepStatus.FAILED:
        return state
    if step_state.status in {HarnessStepStatus.SUCCEEDED, HarnessStepStatus.SKIPPED, HarnessStepStatus.HALTED}:
        return state
    return transition_step(
        state,
        step_id,
        HarnessStepStatus.FAILED,
        error=reason,
        current_step_id=step_id,
        at=at,
    )


def _merge_outputs(
    state: HarnessState,
    step_id: str,
    worker_result: HarnessWorkerResult | None,
) -> HarnessState:
    if worker_result is None:
        return state
    step_spec = _get_step_spec(state, step_id)
    outputs = dict(state.metadata.get("outputs", {})) if isinstance(state.metadata.get("outputs", {}), dict) else {}
    if step_spec.output_key:
        outputs[step_spec.output_key] = worker_result.output
    plan_keys = set(state.metadata.get("plan_keys", ()))
    if "plan_key" in worker_result.output:
        plan_keys.add(str(worker_result.output["plan_key"]))
    claims = set(state.metadata.get("claims", ()))
    claims.update(_coerce_output_sequence(worker_result.output.get("claims", ())))
    questions = set(state.metadata.get("questions", ()))
    questions.update(_coerce_output_sequence(worker_result.output.get("questions", ())))
    evolution_usage = _evolution_usage(state, worker_result)
    return replace(
        state,
        metadata={
            **state.metadata,
            "outputs": outputs,
            "plan_keys": tuple(sorted(plan_keys)),
            "claims": tuple(sorted(claims)),
            "questions": tuple(sorted(questions)),
            **evolution_usage,
        },
    )


def _evolution_usage(state: HarnessState, worker_result: HarnessWorkerResult) -> dict[str, int]:
    output = worker_result.output
    return {
        "evolution_epochs_used": int(state.metadata.get("evolution_epochs_used", 0)) + int(output.get("evolution_epochs", 0)),
        "candidates_used": int(state.metadata.get("candidates_used", 0)) + int(output.get("candidate_count", 0)),
        "patch_operations_used": int(state.metadata.get("patch_operations_used", 0)) + int(output.get("patch_operations", 0)),
        "eval_cases_used": int(state.metadata.get("eval_cases_used", 0)) + int(output.get("eval_cases", 0)),
        "sandbox_runs_used": int(state.metadata.get("sandbox_runs_used", 0)) + int(output.get("sandbox_runs", 0)),
    }


def _run_loop_stop_statuses() -> frozenset[HarnessRunStatus]:
    return terminal_run_statuses().union({HarnessRunStatus.WAITING_APPROVAL, HarnessRunStatus.BLOCKED})


def _coerce_output_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in value)
    return (str(value),)


def _next_transition_time(state: HarnessState):
    return state.updated_at + timedelta(microseconds=1)


def _decision_transition_projection(decision: HarnessDecision) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "decision_type": decision.decision_type.value,
        "step_id": decision.step_id,
        "target_step_id": decision.target_step_id,
        "payload_ref": checksum_for(decision.payload),
    }
    if decision.reason is not None:
        projection["reason_ref"] = checksum_for(decision.reason)
    budget_exhausted = decision.payload.get("budget_exhausted")
    if budget_exhausted is not None:
        projection["budget_exhausted"] = str(budget_exhausted)
    return projection


def _activity_for_state_step(
    state: HarnessState,
    step_id: str,
) -> HarnessActivity | None:
    step = get_step_state(state, step_id)
    metadata = step.metadata
    activity_id = metadata.get("activity_id")
    if activity_id is None:
        return None
    step_spec = _get_step_spec(state, step_id)
    try:
        return HarnessActivity(
            activity_id=str(activity_id),
            run_id=state.run_spec.run_id,
            step_id=step_id,
            attempt=int(metadata.get("activity_attempt", step.attempts)),
            activity_type=str(metadata.get("activity_type", step_spec.worker_type.value)),
            contract_version=str(metadata.get("activity_contract_version")),
            idempotency_key=str(metadata.get("activity_idempotency_key")),
            input_checksum=str(metadata.get("activity_input_checksum")),
            identity_scope_ref=(
                None
                if metadata.get("activity_identity_scope_ref") is None
                else str(metadata["activity_identity_scope_ref"])
            ),
            worker_version=str(metadata.get("activity_worker_version")),
        )
    except (TypeError, ValueError, HarnessValidationError) as exc:
        raise EventIncompleteHistoryError(
            "Harness state contains an incomplete activity descriptor"
        ) from exc


def _activity_result_event_id(state: HarnessState, step_id: str) -> str | None:
    value = get_step_state(state, step_id).metadata.get("activity_result_event_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _task_with_activity(
    task: dict[str, Any],
    activity: HarnessActivity | None,
) -> dict[str, Any]:
    if activity is None:
        return dict(task)
    return {
        **task,
        "harness_activity": {
            "activity_id": activity.activity_id,
            "idempotency_key": activity.idempotency_key,
            "attempt": activity.attempt,
            "contract_version": activity.contract_version,
        },
    }


def _in_memory_called_activity_ids(
    *,
    state: HarnessState | None,
    transitions: tuple[HarnessTransitionCommitted, ...],
    events: tuple[HarnessEvent, ...],
) -> frozenset[str]:
    if (
        state is None
        or not transitions
        or transitions[-1].transition_kind != HarnessTransitionKind.EXECUTE_ENTRY
        or state.current_step_id is None
    ):
        return frozenset()
    activity = _activity_for_state_step(state, state.current_step_id)
    if activity is None:
        return frozenset()
    transition_id = transitions[-1].transition_id
    try:
        transition_index = next(
            index
            for index, event in enumerate(events)
            if event.event_id == transition_id
        )
    except StopIteration as exc:
        raise EventStoreCorruptionError(
            "Harness in-memory history is missing its execute entry"
        ) from exc
    markers = tuple(
        event
        for event in events[transition_index + 1 :]
        if event.event_type == HarnessEventType.WORKER_CALLED
    )
    if not markers:
        return frozenset()
    if len(markers) != 1:
        raise EventStoreCorruptionError(
            "Harness execute entry has duplicate worker call markers"
        )
    marker = markers[0]
    if marker.run_id != state.run_spec.run_id or marker.step_id != activity.step_id:
        raise EventStoreCorruptionError(
            "Harness worker call marker context conflicts with activity"
        )
    validate_activity_call_marker(
        marker.payload,
        expected_activity=activity,
    )
    return frozenset({activity.activity_id})


def _validate_recovered_gate_results(
    transition: HarnessTransitionCommitted,
    gate_results: tuple[HarnessGateResult, ...],
) -> None:
    gate_ref = checksum_for(tuple(result.to_dict() for result in gate_results))
    if transition.gate_ref != gate_ref:
        raise EventReplayMismatchError(
            sequence=transition.stream_sequence or transition.state_version,
            reason="Harness deterministic gate result conflicts with durable history",
        )


def _phase_entry_evaluation_state(
    recovery: HarnessRecovery,
    *,
    expected_entry: HarnessTransitionKind,
) -> HarnessState:
    if recovery.state is None or len(recovery.transitions) < 2:
        raise EventIncompleteHistoryError(
            "Harness phase exit is missing its committed entry transition"
        )
    entry = recovery.transitions[-2]
    if entry.transition_kind != expected_entry:
        raise EventIncompleteHistoryError(
            "Harness phase exit does not follow its committed entry transition"
        )
    entry_state = entry.state.restore(recovery.state.run_spec)
    hydrated_steps = {
        step.step_id: step for step in recovery.state.step_states
    }
    return replace(
        entry_state,
        step_states=tuple(
            replace(
                step,
                metadata=hydrated_steps[step.step_id].metadata,
            )
            for step in entry_state.step_states
        ),
        metadata=recovery.state.metadata,
    )


def _terminal_transition_kind(
    status: HarnessRunStatus,
    decision: HarnessDecision,
) -> HarnessTransitionKind:
    if status == HarnessRunStatus.SUCCEEDED:
        return HarnessTransitionKind.SUCCESS
    if status == HarnessRunStatus.FAILED:
        return HarnessTransitionKind.FAILURE
    if status == HarnessRunStatus.CANCELLED:
        return HarnessTransitionKind.CANCEL
    if status == HarnessRunStatus.BLOCKED:
        return HarnessTransitionKind.WAIT
    if (
        status == HarnessRunStatus.HALTED
        and decision.payload.get("budget_exhausted") is not None
    ):
        return HarnessTransitionKind.BUDGET_EXHAUSTION
    return HarnessTransitionKind.HALT


__all__ = ["HarnessControlPlane", "HarnessRunResult", "InMemoryHarnessEventPort"]
