from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Iterable

from framework.harness.control_plane.decision import HarnessDecision, HarnessDecisionType
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
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
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus

if TYPE_CHECKING:
    from framework.harness.ports import HarnessEventPort


WorkerCallable = Callable[[dict[str, Any]], HarnessWorkerResult]


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

    def record(self, event: HarnessEvent) -> HarnessEvent:
        self.events.append(event)
        return event


class HarnessControlPlane:
    def __init__(
        self,
        *,
        scheduler: HarnessScheduler | None = None,
        event_port: HarnessEventPort | None = None,
        worker_registry: dict[str, WorkerCallable | Iterable[HarnessWorkerResult]] | None = None,
        plan_gates: tuple[DeterministicGate, ...] | None = None,
        verify_gates: tuple[DeterministicGate, ...] | None = None,
    ) -> None:
        if event_port is None:
            raise HarnessValidationError(
                "Harness event_port is required; inject InMemoryHarnessEventPort explicitly only in tests"
            )
        self.scheduler = scheduler or HarnessScheduler()
        self.event_port = event_port
        self.worker_registry = dict(worker_registry or {})
        self.plan_gates = plan_gates or default_plan_gates()
        self.verify_gates = verify_gates or default_verify_gates()
        self._iterable_workers: dict[str, list[HarnessWorkerResult]] = {}
        self._committed_events: list[HarnessEvent] = []

    def initialize(self, run_spec: HarnessRunSpec) -> HarnessState:
        state = HarnessState.initial(run_spec)
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id=run_spec.run_id,
                occurred_at=run_spec.created_at,
            )
        )
        return state

    def run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        state = self.initialize(run_spec)
        return self._drive(state)

    def resume_after_approval(
        self,
        state: HarnessState,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> HarnessRunResult:
        """Durably resume or cancel one approval-waiting Harness projection."""

        if not isinstance(state, HarnessState):
            raise TypeError("state must be HarnessState")
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
            self._record_decision(decision)
            cancelled = self._commit_step_transition(
                state,
                step_id,
                HarnessStepStatus.HALTED,
                transition_kind="approval_cancel",
                error=decision.reason,
                current_step_id=step_id,
            )
            cancelled = self._commit_run_transition(
                cancelled,
                HarnessRunStatus.CANCELLED,
                transition_kind="approval_cancel",
                metadata={"terminal_reason": decision.reason},
            )
            return self._result(cancelled, decisions=[decision])

        # Recovery may have only an integrity summary for the worker activity.
        # Prove the complete recorded result is available before committing any
        # approval-resume transition; otherwise fail closed at the old state.
        worker_result = _worker_result_from_step_state(get_step_state(state, step_id))
        decision = HarnessDecision(
            decision_type=HarnessDecisionType.RESUME_AFTER_APPROVAL,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason=reason or "Harness approval granted",
            payload={"approval_outcome": "approved"},
        )
        self._record_decision(decision)
        resumed = self._commit_run_transition(
            state,
            HarnessRunStatus.RUNNING,
            transition_kind="approval_resume",
        )
        resumed = self._commit_step_transition(
            resumed,
            step_id,
            HarnessStepStatus.RUNNING,
            transition_kind="approval_resume",
            metadata={"approval_granted": True},
            current_step_id=step_id,
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
    ) -> HarnessRunResult:
        decisions: list[HarnessDecision] = list(initial_decisions or ())
        worker_results: dict[str, HarnessWorkerResult] = {}
        quality_verdicts: dict[str, HarnessQualityVerdict] = {}
        gate_results: tuple[HarnessGateResult, ...] = ()
        quality_verdict: HarnessQualityVerdict | None = None

        while state.status not in _run_loop_stop_statuses():
            decision = self.scheduler.next_decision(
                state,
                worker_result=worker_result,
                quality_verdict=quality_verdict,
                gate_results=gate_results,
            )
            self._record_decision(decision)
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
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.RUNNING,
                transition_kind="run_start",
            )
        return state

    def _plan_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
    ) -> tuple[HarnessState, tuple[HarnessGateResult, ...]]:
        step_id = _require_step(decision)
        self._record_phase(state, HarnessPhase.PLAN, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)
        if state.status in {HarnessRunStatus.RUNNING, HarnessRunStatus.REPLANNING}:
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.PLANNING,
                transition_kind="plan_entry",
            )
        state = self._commit_step_transition(
            state,
            step_id,
            HarnessStepStatus.PLANNING,
            transition_kind="plan_entry",
            turn_increment=1,
            current_step_id=step_id,
        )
        gate_results = self._evaluate_gates(self.plan_gates, state, step_id, worker_result=None, quality_verdict=None)
        self._record_phase(
            state,
            HarnessPhase.PLAN,
            step_id,
            gate_results,
            boundary=HarnessPhaseBoundary.EXIT,
        )
        if all(result.passed for result in gate_results):
            state = self._commit_step_transition(
                state,
                step_id,
                HarnessStepStatus.PLAN_VERIFIED,
                transition_kind="plan_exit",
                current_step_id=step_id,
            )
        return state, gate_results

    def _execute_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
    ) -> tuple[HarnessState, HarnessWorkerResult]:
        step_id = _require_step(decision)
        self._record_phase(state, HarnessPhase.EXECUTE, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)
        if state.status in {HarnessRunStatus.PLANNING, HarnessRunStatus.RUNNING, HarnessRunStatus.EXECUTING}:
            if state.status != HarnessRunStatus.EXECUTING:
                state = self._commit_run_transition(
                    state,
                    HarnessRunStatus.EXECUTING,
                    transition_kind="execute_entry",
                )
        step_state = get_step_state(state, step_id)
        state = self._commit_step_transition(
            state,
            step_id,
            HarnessStepStatus.RUNNING,
            transition_kind=(
                "retry_execute_entry"
                if step_state.status == HarnessStepStatus.RETRYING
                else "execute_entry"
            ),
            attempts=step_state.attempts + 1,
            turn_increment=1,
            worker_call_increment=1,
            current_step_id=step_id,
        )
        step_spec = _get_step_spec(state, step_id)
        worker_result = self._call_worker(step_spec, state)
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.WORKER_RESULT_RECORDED,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                payload=worker_result.to_dict(),
            )
        )
        self._record_phase(
            state,
            HarnessPhase.EXECUTE,
            step_id,
            (),
            boundary=HarnessPhaseBoundary.EXIT,
        )
        state = replace_step_state(
            state,
            replace(
                get_step_state(state, step_id),
                output_ref=step_spec.output_key if worker_result.status == HarnessWorkerStatus.SUCCEEDED else None,
                error=worker_result.error,
                metadata={**get_step_state(state, step_id).metadata, "worker_result": worker_result.to_dict()},
            ),
            current_step_id=step_id,
        )
        return state, worker_result

    def _verify_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        worker_result: HarnessWorkerResult | None,
    ) -> tuple[HarnessState, tuple[HarnessGateResult, ...], HarnessQualityVerdict | None]:
        step_id = _require_step(decision)
        self._record_phase(state, HarnessPhase.VERIFY, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)
        if state.status == HarnessRunStatus.EXECUTING:
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.VERIFYING,
                transition_kind="verify_entry",
            )
        step_state = get_step_state(state, step_id)
        if step_state.status == HarnessStepStatus.RUNNING:
            state = self._commit_step_transition(
                state,
                step_id,
                HarnessStepStatus.VERIFYING,
                transition_kind="verify_entry",
                current_step_id=step_id,
                turn_increment=1,
            )
        else:
            state = replace_step_state(state, step_state, current_step_id=step_id, turn_increment=1)
        quality_verdict = self._quality_verdict(state, step_id, worker_result)
        gate_results = self._evaluate_gates(
            self.verify_gates,
            state,
            step_id,
            worker_result=worker_result,
            quality_verdict=quality_verdict,
        )
        self._record_phase(
            state,
            HarnessPhase.VERIFY,
            step_id,
            gate_results,
            boundary=HarnessPhaseBoundary.EXIT,
        )
        return state, gate_results, quality_verdict

    def _complete_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessState:
        step_id = _require_step(decision)
        state = self._commit_step_transition(
            state,
            step_id,
            HarnessStepStatus.SUCCEEDED,
            transition_kind="step_success",
            metadata={"worker_result": worker_result.to_dict() if worker_result is not None else None},
            current_step_id=step_id,
        )
        state = _merge_outputs(state, step_id, worker_result)
        if state.status == HarnessRunStatus.VERIFYING:
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.RUNNING,
                transition_kind="verify_complete",
            )
        return state

    def _route_to_step(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        target_step_id = decision.target_step_id or state.run_spec.workflow.entry_step_id
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.RUNNING,
                transition_kind="route_to_step",
            )
        step_state = get_step_state(state, target_step_id)
        if step_state.status == HarnessStepStatus.PENDING:
            return replace(state, current_step_id=target_step_id)
        reset_step = replace(
            step_state,
            status=HarnessStepStatus.PENDING,
            error=None,
            metadata={**step_state.metadata, "rerouted": True},
        )
        candidate = replace_step_state(state, reset_step, current_step_id=target_step_id)
        self._record_step_change(
            state,
            candidate,
            target_step_id,
            transition_kind="route_to_step",
        )
        return candidate

    def _route_to_repair(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        if decision.step_id:
            candidate = _fail_current_step(state, decision.step_id, decision.reason)
            if candidate is not state:
                self._record_step_change(
                    state,
                    candidate,
                    decision.step_id,
                    transition_kind="route_to_repair",
                )
                state = candidate
        state = self._route_to_step(state, decision)
        return replace(state, metadata={**state.metadata, "repair_from_step_id": decision.step_id})

    def _retry_step(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        step_id = _require_step(decision)
        state = self._commit_step_transition(
            state,
            step_id,
            HarnessStepStatus.RETRYING,
            transition_kind="retry",
            current_step_id=step_id,
            error=decision.reason,
        )
        if state.status == HarnessRunStatus.EXECUTING:
            return state
        return self._commit_run_transition(
            state,
            HarnessRunStatus.EXECUTING,
            transition_kind="retry",
        )

    def _replan_step(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        step_id = _require_step(decision)
        self._record_phase(state, HarnessPhase.REPLAN, step_id, (), boundary=HarnessPhaseBoundary.ENTRY)
        if state.status in {HarnessRunStatus.PLANNING, HarnessRunStatus.VERIFYING}:
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.REPLANNING,
                transition_kind="replan",
            )
        step_state = get_step_state(state, step_id)
        state = self._commit_step_transition(
            state,
            step_id,
            HarnessStepStatus.REPLANNING,
            transition_kind="replan",
            replans=step_state.replans + 1,
            replan_increment=1,
            current_step_id=step_id,
            error=decision.reason,
        )
        self._record_phase(state, HarnessPhase.REPLAN, step_id, (), boundary=HarnessPhaseBoundary.EXIT)
        return state

    def _wait_for_approval(self, state: HarnessState, decision: HarnessDecision) -> HarnessState:
        step_id = _require_step(decision)
        if state.status in {HarnessRunStatus.RUNNING, HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = self._commit_run_transition(
                state,
                HarnessRunStatus.WAITING_APPROVAL,
                transition_kind="wait_for_approval",
            )
        step_state = get_step_state(state, step_id)
        if step_state.status != HarnessStepStatus.WAITING_APPROVAL:
            state = self._commit_step_transition(
                state,
                step_id,
                HarnessStepStatus.WAITING_APPROVAL,
                transition_kind="wait_for_approval",
                error=decision.reason,
            )
        return state

    def _finish_run(self, state: HarnessState, status: HarnessRunStatus, decision: HarnessDecision) -> HarnessState:
        if status == HarnessRunStatus.HALTED and decision.step_id:
            self._record_phase(
                state,
                HarnessPhase.HALT,
                decision.step_id,
                (),
                boundary=HarnessPhaseBoundary.ENTRY,
            )
            candidate = _halt_current_step(state, decision.step_id, decision.reason)
            if candidate is not state:
                self._record_step_change(
                    state,
                    candidate,
                    decision.step_id,
                    transition_kind="halt",
                )
                state = candidate
            self._record_phase(
                state,
                HarnessPhase.HALT,
                decision.step_id,
                (),
                boundary=HarnessPhaseBoundary.EXIT,
            )
        if status == HarnessRunStatus.FAILED and decision.step_id:
            candidate = _fail_current_step(state, decision.step_id, decision.reason)
            if candidate is not state:
                self._record_step_change(
                    state,
                    candidate,
                    decision.step_id,
                    transition_kind="failure",
                )
                state = candidate
        return self._commit_run_transition(
            state,
            status,
            transition_kind=_terminal_transition_kind(status, decision.reason),
            metadata={"terminal_reason": decision.reason},
        )

    def _evaluate_gates(
        self,
        gates: tuple[DeterministicGate, ...],
        state: HarnessState,
        step_id: str,
        *,
        worker_result: HarnessWorkerResult | None,
        quality_verdict: HarnessQualityVerdict | None,
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

    def _call_worker(self, step_spec: HarnessStepSpec, state: HarnessState) -> HarnessWorkerResult:
        worker = self.worker_registry.get(step_spec.step_id) or self.worker_registry.get(step_spec.worker_type.value)
        outputs = state.metadata.get("outputs", {})
        prior_outputs = outputs if isinstance(outputs, dict) else {}
        task = {
            "run_id": state.run_spec.run_id,
            "step_id": step_spec.step_id,
            "worker_type": step_spec.worker_type.value,
            "inputs": {
                key: prior_outputs[key] if key in prior_outputs else state.run_spec.inputs.get(key)
                for key in step_spec.input_keys
            },
            "metadata": step_spec.metadata,
        }
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.WORKER_CALLED,
                run_id=state.run_spec.run_id,
                step_id=step_spec.step_id,
                payload=task,
            )
        )
        if worker is None:
            return HarnessWorkerResult(status=HarnessWorkerStatus.SUCCEEDED, output={})
        if callable(worker):
            return worker(task)
        execute = getattr(worker, "execute", None)
        if callable(execute):
            return execute(task)
        if step_spec.worker_type.value == "llm":
            generate = getattr(worker, "generate", None)
            if callable(generate):
                return generate(task)
        if step_spec.worker_type.value == "skill":
            run_skill = getattr(worker, "run_skill", None)
            if callable(run_skill):
                return run_skill(str(task.get("skill_name", task["step_id"])), dict(task.get("inputs", {})), dict(task.get("context", {})))
        if step_spec.worker_type.value == "subagent":
            run_subagent = getattr(worker, "run_subagent", None)
            if callable(run_subagent):
                return run_subagent(str(task.get("subagent_id", task["step_id"])), dict(task), dict(task.get("budget", {})))
        try:
            queued = self._iterable_workers.setdefault(step_spec.step_id, list(worker))
        except TypeError as exc:
            raise HarnessValidationError("worker registry value must be callable, a Harness worker port, or result iterable") from exc
        if not queued:
            return HarnessWorkerResult(status=HarnessWorkerStatus.FAILED, error="fake worker queue is exhausted")
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

    def _record_decision(self, decision: HarnessDecision) -> None:
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.DECISION_RECORDED,
                run_id=decision.run_id,
                step_id=decision.step_id,
                payload=decision.to_dict(),
                occurred_at=decision.decided_at,
            )
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

    def _commit_run_transition(
        self,
        state: HarnessState,
        status: HarnessRunStatus,
        *,
        transition_kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessState:
        candidate = transition_run(state, status, metadata=metadata)
        self._record_state_change(
            state,
            candidate,
            transition_kind=transition_kind,
        )
        return candidate

    def _commit_step_transition(
        self,
        state: HarnessState,
        step_id: str,
        status: HarnessStepStatus,
        *,
        transition_kind: str,
        **kwargs: Any,
    ) -> HarnessState:
        candidate = transition_step(state, step_id, status, **kwargs)
        self._record_step_change(
            state,
            candidate,
            step_id,
            transition_kind=transition_kind,
        )
        return candidate

    def _record_event(self, event: HarnessEvent) -> HarnessEvent:
        committed = self.event_port.record(event)
        if not isinstance(committed, HarnessEvent):
            raise HarnessValidationError(
                "Harness event_port must return the authoritative committed HarnessEvent projection"
            )
        if (
            committed.event_id != event.event_id
            or committed.run_id != event.run_id
            or committed.step_id != event.step_id
            or committed.event_type != event.event_type
        ):
            raise HarnessValidationError("Harness event_port returned a conflicting committed projection")
        self._committed_events.append(committed)
        return committed

    def _result(
        self,
        state: HarnessState,
        *,
        decisions: list[HarnessDecision],
        worker_results: dict[str, HarnessWorkerResult] | None = None,
        quality_verdicts: dict[str, HarnessQualityVerdict] | None = None,
    ) -> HarnessRunResult:
        run_id = state.run_spec.run_id
        return HarnessRunResult(
            state=state,
            decisions=tuple(decisions),
            events=tuple(event for event in self._committed_events if event.run_id == run_id),
            worker_results={
                key: value
                for key, value in (worker_results or {}).items()
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


def _get_step_spec(state: HarnessState, step_id: str) -> HarnessStepSpec:
    for step in state.run_spec.workflow.steps:
        if step.step_id == step_id:
            return step
    raise LookupError(step_id)


def _ensure_run_status(
    state: HarnessState,
    status: HarnessRunStatus,
    *,
    metadata: dict[str, Any] | None = None,
) -> HarnessState:
    if state.status == status:
        return replace(state, metadata={**state.metadata, **(metadata or {})})
    return transition_run(state, status, metadata=metadata)


def _halt_current_step(state: HarnessState, step_id: str, reason: str | None) -> HarnessState:
    step_state = get_step_state(state, step_id)
    if step_state.status == HarnessStepStatus.HALTED:
        return state
    if step_state.status in {HarnessStepStatus.SUCCEEDED, HarnessStepStatus.FAILED, HarnessStepStatus.SKIPPED}:
        return state
    return transition_step(state, step_id, HarnessStepStatus.HALTED, error=reason, current_step_id=step_id)


def _fail_current_step(state: HarnessState, step_id: str, reason: str | None) -> HarnessState:
    step_state = get_step_state(state, step_id)
    if step_state.status == HarnessStepStatus.FAILED:
        return state
    if step_state.status in {HarnessStepStatus.SUCCEEDED, HarnessStepStatus.SKIPPED, HarnessStepStatus.HALTED}:
        return state
    return transition_step(state, step_id, HarnessStepStatus.FAILED, error=reason, current_step_id=step_id)


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


def _worker_result_from_step_state(step_state: HarnessStepState) -> HarnessWorkerResult:
    payload = step_state.metadata.get("worker_result")
    if not isinstance(payload, dict):
        raise HarnessValidationError(
            "approval resume requires the committed worker result projection"
        )
    output = payload.get("output", {})
    diagnostics = payload.get("diagnostics", {})
    metrics = payload.get("metrics", {})
    artifacts = payload.get("artifacts", ())
    if not isinstance(output, dict) or not isinstance(diagnostics, dict) or not isinstance(metrics, dict):
        raise HarnessValidationError("approval resume worker result projection is invalid")
    if not isinstance(artifacts, list | tuple):
        raise HarnessValidationError("approval resume worker artifacts projection is invalid")
    return HarnessWorkerResult(
        status=payload.get("status"),
        output=output,
        artifacts=tuple(str(item) for item in artifacts),
        diagnostics=diagnostics,
        metrics=metrics,
        error=payload.get("error"),
    )


def _terminal_transition_kind(status: HarnessRunStatus, reason: str | None) -> str:
    if status == HarnessRunStatus.SUCCEEDED:
        return "success"
    if status == HarnessRunStatus.FAILED:
        return "failure"
    if status == HarnessRunStatus.CANCELLED:
        return "cancel"
    if status == HarnessRunStatus.BLOCKED:
        return "wait"
    if status == HarnessRunStatus.HALTED and "budget" in str(reason or "").lower():
        return "budget_exhaustion"
    return "halt"


__all__ = ["HarnessControlPlane", "HarnessRunResult", "InMemoryHarnessEventPort"]
