from __future__ import annotations

from typing import Any

from framework.harness.control_plane.decision import HarnessDecision, HarnessDecisionType
from framework.harness.control_plane.gates import HarnessGateResult, all_gates_passed
from framework.harness.control_plane.routing import HarnessRoutingEvaluator
from framework.harness.control_plane.state import HarnessRunStatus, HarnessState, HarnessStepStatus
from framework.harness.control_plane.transitions import get_step_state, terminal_run_statuses
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus


class HarnessScheduler:
    def __init__(self, routing_evaluator: HarnessRoutingEvaluator | None = None) -> None:
        self._routing = routing_evaluator or HarnessRoutingEvaluator()

    def next_decision(
        self,
        state: HarnessState,
        *,
        worker_result: HarnessWorkerResult | None = None,
        quality_verdict: HarnessQualityVerdict | None = None,
        gate_results: tuple[HarnessGateResult, ...] = (),
    ) -> HarnessDecision:
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
            return HarnessDecision(decision_type=HarnessDecisionType.PLAN_STEP, run_id=run_id, step_id=step_id)
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
            return self._after_step_success(state, worker_result=worker_result, quality_verdict=quality_verdict)
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

    def _after_plan(self, state: HarnessState, gate_results: tuple[HarnessGateResult, ...]) -> HarnessDecision:
        step_id = state.current_step_id
        if not step_id:
            return HarnessDecision(decision_type=HarnessDecisionType.FAIL_RUN, run_id=state.run_spec.run_id)
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
            payload={"gate_results": [result.to_dict() for result in gate_results]},
        )

    def _after_execute(
        self,
        state: HarnessState,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessDecision:
        step_id = step_spec.step_id
        if worker_result is None:
            return HarnessDecision(decision_type=HarnessDecisionType.EXECUTE_STEP, run_id=state.run_spec.run_id, step_id=step_id)
        if worker_result.status == HarnessWorkerStatus.SUCCEEDED:
            if (
                step_spec.metadata.get("approval_required") is True
                and not get_step_state(state, step_id).metadata.get("approval_granted")
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
            return HarnessDecision(decision_type=HarnessDecisionType.VERIFY_STEP, run_id=state.run_spec.run_id, step_id=step_id)
        if worker_result.status == HarnessWorkerStatus.WAITING_APPROVAL:
            return HarnessDecision(
                decision_type=HarnessDecisionType.WAIT_FOR_APPROVAL,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="worker is waiting for approval",
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
                reason=worker_result.error or "worker failed; route to configured repair step",
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
            return HarnessDecision(decision_type=HarnessDecisionType.COMPLETE_STEP, run_id=state.run_spec.run_id, step_id=step_id)
        failed_results = [result.to_dict() for result in gate_results if not result.passed]
        repair_step_id = step_spec.retry_policy.repair_step_id or step_spec.metadata.get("repair_step_id")
        if repair_step_id:
            return HarnessDecision(
                decision_type=HarnessDecisionType.ROUTE_TO_REPAIR,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                target_step_id=str(repair_step_id),
                reason="verification failed; route to repair step",
                payload={"gate_results": failed_results, "quality_verdict": _verdict_payload(quality_verdict)},
            )
        if self._can_replan(state):
            return HarnessDecision(
                decision_type=HarnessDecisionType.REPLAN_STEP,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="verification failed",
                payload={"gate_results": failed_results, "quality_verdict": _verdict_payload(quality_verdict)},
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.HALT_RUN,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason="verification failed and replan budget is exhausted",
            payload={"gate_results": failed_results, "quality_verdict": _verdict_payload(quality_verdict)},
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
            return HarnessDecision(decision_type=HarnessDecisionType.COMPLETE_RUN, run_id=state.run_spec.run_id)
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

    def _execute_or_halt(self, state: HarnessState, step_id: str, *, reason: str | None = None) -> HarnessDecision:
        budget_decision = self._turn_budget_decision(state, step_id)
        if budget_decision is not None:
            return budget_decision
        if state.worker_call_count >= state.run_spec.budget.max_worker_calls:
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="worker call budget is exhausted",
            )
        return HarnessDecision(
            decision_type=HarnessDecisionType.EXECUTE_STEP,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason=reason,
        )

    def _turn_budget_decision(self, state: HarnessState, step_id: str | None) -> HarnessDecision | None:
        budget = state.run_spec.budget
        if state.turn_count >= budget.max_turns:
            return HarnessDecision(
                decision_type=HarnessDecisionType.HALT_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason="turn budget is exhausted",
                payload={"turn_count": state.turn_count, "max_turns": budget.max_turns},
            )
        return None

    def _can_replan(self, state: HarnessState) -> bool:
        if state.current_step_id is None:
            return False
        step_state = get_step_state(state, state.current_step_id)
        return state.replan_count < state.run_spec.budget.max_replans and step_state.replans < state.run_spec.budget.max_replans

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


def _get_step_spec(workflow: HarnessWorkflowSpec, step_id: str) -> HarnessStepSpec:
    for step in workflow.steps:
        if step.step_id == step_id:
            return step
    raise LookupError(step_id)


def _error_type(worker_result: HarnessWorkerResult) -> str | None:
    diagnostics = worker_result.diagnostics if isinstance(getattr(worker_result, "diagnostics", {}), dict) else {}
    value: Any = diagnostics.get("error_type")
    if value is None:
        value = worker_result.output.get("error_type")
    return str(value) if value is not None else None


def _verdict_payload(verdict: HarnessQualityVerdict | None) -> dict[str, Any] | None:
    return verdict.to_dict() if verdict is not None else None


__all__ = ["HarnessScheduler"]
