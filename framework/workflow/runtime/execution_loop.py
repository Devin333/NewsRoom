from __future__ import annotations

import time
from typing import Any, Callable

from framework.events.trace import TraceContext
from framework.specs import EdgeCondition, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.runtime.checkpoint_coordinator import (
    CheckpointCoordinator,
    checkpoint_created_payload,
)
from framework.workflow.runtime.event_emitter import WorkflowEventFact
from framework.workflow.runtime.execution_context import WorkflowExecutionContext
from framework.workflow.runtime.manifest_updater import ManifestUpdater
from framework.workflow.runtime.result import StepOutcome, WorkflowError
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge
from framework.workflow.runtime.state_machine import (
    WorkflowRuntimeEvent,
    WorkflowRuntimeEventType,
    WorkflowStateMachine,
)
from framework.workflow.runtime.step_invoker import StepInvoker, is_budget_exceeded_outcome
from framework.workflow.runtime.timeout import WorkflowTimeoutBudget, workflow_timeout_budget
from framework.workflow.routing import RoutingEngine


class WorkflowExecutionLoop:
    def __init__(
        self,
        *,
        state_machine: WorkflowStateMachine,
        routing_engine: RoutingEngine,
        step_invoker: StepInvoker,
        checkpoint_coordinator: CheckpointCoordinator,
        event_bridge: RuntimeEventBridge,
        manifest_updater: ManifestUpdater,
        is_run_cancelled: Callable[[str], bool],
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self._state_machine = state_machine
        self._routing_engine = routing_engine
        self._step_invoker = step_invoker
        self._checkpoint_coordinator = checkpoint_coordinator
        self._event_bridge = event_bridge
        self._manifest_updater = manifest_updater
        self._is_run_cancelled = is_run_cancelled
        self._monotonic_fn = monotonic_fn or time.monotonic

    def run(self, context: WorkflowExecutionContext) -> None:
        workflow = context.workflow
        set_clock = getattr(self._step_invoker, "set_clock", None)
        if callable(set_clock):
            set_clock(self._monotonic_fn)
        timeout_budget = workflow_timeout_budget(
            workflow,
            started_monotonic=context.started_monotonic,
            reserve_seconds=context.execution_limits.root_reserve_seconds,
        )
        while context.current_step_ids:
            if self._timeout_if_exceeded(
                context,
                timeout_budget,
                pending_step_id=context.current_step_ids[0],
            ):
                self._write_checkpoint(context)
                break
            if self._cancel_if_requested(context):
                break
            current_step_id = context.current_step_ids.pop(0)
            if self._stop_if_loop_limit_exceeded(context, current_step_id):
                break

            step = workflow.step_by_id(current_step_id)
            outcome = self._invoke_step(context, step)
            if self._timeout_if_exceeded(context, timeout_budget, step_id=step.step_id):
                self._write_checkpoint(context)
                break
            stop_after_checkpoint = self._handle_step_outcome(context, step, outcome)
            if stop_after_checkpoint:
                break
            # Only checkpoint non-idempotent steps; idempotent steps can be
            # safely re-run from the previous checkpoint, avoiding redundant I/O.
            if not step.idempotent:
                self._write_checkpoint(context)

    def _timeout_if_exceeded(
        self,
        context: WorkflowExecutionContext,
        timeout_budget: WorkflowTimeoutBudget | None,
        *,
        step_id: str | None = None,
        pending_step_id: str | None = None,
    ) -> bool:
        if timeout_budget is None:
            return False
        now_monotonic = self._monotonic_fn()
        if not timeout_budget.is_exceeded(now_monotonic):
            return False
        context.execution_limits.cancel_event.set()
        details = timeout_budget.details(now_monotonic)
        if step_id is not None:
            details["step_id"] = step_id
        if pending_step_id is not None:
            details["pending_step_id"] = pending_step_id
        error = WorkflowError(
            error_type="WorkflowTimeoutExceeded",
            message=(
                "workflow exceeded timeout of "
                f"{timeout_budget.timeout_seconds:g} seconds"
            ),
            step_id=step_id,
            details=details,
        )
        trace_context = (
            context.step_trace_contexts.get(step_id)
            if step_id is not None
            else context.trace_context
        )
        self._commit_terminal_transition(
            context,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.FAIL,
                reason="workflow_timeout_exceeded",
                step_id=step_id,
                metadata=details,
            ),
            error=error,
            trace_context=trace_context,
            before_terminal_event=lambda: context.recorder.emit(
                "workflow_timeout_exceeded",
                {
                    "run_id": context.run_id,
                    "workflow_id": context.workflow.workflow_id,
                    "timeout_seconds": details["timeout_seconds"],
                    "elapsed_seconds": details["elapsed_seconds"],
                    "policy_source": details["policy_source"],
                    **({"step_id": step_id} if step_id is not None else {}),
                    **(
                        {"pending_step_id": pending_step_id}
                        if pending_step_id is not None
                        else {}
                    ),
                },
                trace_context=trace_context,
            ),
        )
        context.current_step_ids = []
        context.manifest["runtime_timeout"] = {"exceeded": True, **details}
        return True

    def _cancel_if_requested(self, context: WorkflowExecutionContext) -> bool:
        if not self._is_run_cancelled(context.run_id):
            return False
        context.execution_limits.cancel_event.set()
        commit_workflow_transition(
            context=context,
            state_machine=self._state_machine,
            event=WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.CANCEL,
                reason="cancel marker found",
            ),
            append=lambda _status: context.recorder.emit(
                "workflow_cancelled",
                {"run_id": context.run_id},
            ),
        )
        context.current_step_ids = []
        return True

    def _stop_if_loop_limit_exceeded(
        self,
        context: WorkflowExecutionContext,
        current_step_id: str,
    ) -> bool:
        visit_count = context.step_visit_counts.get(current_step_id, 0) + 1
        if visit_count <= context.workflow.max_step_visits:
            context.step_visit_counts[current_step_id] = visit_count
            return False
        error = WorkflowError(
            error_type="WorkflowLoopLimitExceeded",
            message=(
                f"step visit limit exceeded for {current_step_id}: "
                f"{context.workflow.max_step_visits}"
            ),
            step_id=current_step_id,
            details={
                "max_step_visits": context.workflow.max_step_visits,
                "visit_count": visit_count,
            },
        )
        trace_context = self._step_trace_context(context, current_step_id)
        self._commit_terminal_transition(
            context,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.FAIL,
                reason="workflow_loop_limit_exceeded",
                step_id=current_step_id,
                metadata={
                    "max_step_visits": context.workflow.max_step_visits,
                    "visit_count": visit_count,
                },
            ),
            error=error,
            trace_context=trace_context,
            before_terminal_event=lambda: context.recorder.emit(
                "workflow_loop_limit_exceeded",
                {
                    "step_id": current_step_id,
                    "max_step_visits": context.workflow.max_step_visits,
                    "visit_count": visit_count,
                },
                trace_context=trace_context,
            ),
        )
        context.step_visit_counts[current_step_id] = visit_count
        context.current_step_ids = []
        return True

    def _invoke_step(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
    ) -> StepOutcome:
        context.path.append(step.step_id)
        step_trace = self._step_trace_context(context, step.step_id)
        context.manifest.setdefault("step_spans", {})[step.step_id] = {
            "step_id": step.step_id,
            "span_id": step_trace.span_id,
            "parent_span_id": step_trace.parent_span_id,
            "trace_id": step_trace.trace_id,
        }
        self._manifest_updater.write_step_policy_input_artifact(step, context.buffer)
        outcome = self._step_invoker.run_step_with_retries(
            step,
            context.buffer,
            context.recorder,
            trace_context=step_trace,
            execution_limits=context.execution_limits,
        )
        self._event_bridge.emit_agent_loop_stream_events(
            context.recorder,
            step,
            outcome,
            trace_context=step_trace,
        )
        self._event_bridge.emit_memory_operation_events(
            context.recorder,
            step,
            outcome,
            trace_context=step_trace,
        )
        outcome = self._manifest_updater.write_llm_call_artifacts(step, outcome)
        self._manifest_updater.sync_llm_call_artifacts_to_buffer(
            context.buffer,
            step,
            outcome,
        )
        outcome = self._manifest_updater.finalize_step_outcome_contract(
            context.workflow,
            step,
            outcome,
            trace_context=step_trace,
            checkpoint_available=self._checkpoint_coordinator.has_checkpoint_store(),
        )
        self._manifest_updater.write_step_policy_terminal_artifact(step, outcome)
        self._manifest_updater.record_step_outcome(
            step=step,
            outcome=outcome,
            path=context.path,
            step_results=context.step_results,
        )
        return outcome

    @staticmethod
    def _step_trace_context(
        context: WorkflowExecutionContext,
        step_id: str,
    ) -> TraceContext:
        step_trace = context.step_trace_contexts.get(step_id)
        if step_trace is None:
            step_trace = context.trace_context.child(
                step_id=step_id,
            )
            context.step_trace_contexts[step_id] = step_trace
        return step_trace

    def _commit_terminal_transition(
        self,
        context: WorkflowExecutionContext,
        event: WorkflowRuntimeEvent,
        *,
        error: WorkflowError,
        trace_context: TraceContext | None,
        before_terminal_event: Callable[[], Any] | None = None,
    ) -> WorkflowStatus:
        def append(next_status: WorkflowStatus) -> None:
            if before_terminal_event is not None:
                before_terminal_event()
            self._event_bridge.emit_terminal_workflow_event(
                context.recorder,
                status=next_status,
                path=context.path,
                error=error,
                trace_context=trace_context,
            )

        next_status = commit_workflow_transition(
            context=context,
            state_machine=self._state_machine,
            event=event,
            append=append,
        )
        context.error = error
        return next_status

    def _handle_step_outcome(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> bool:
        if outcome.status == StepStatus.SUCCEEDED:
            self._handle_success(context, step, outcome)
            return False
        if outcome.status == StepStatus.PAUSED:
            self._handle_pause(context, step, outcome)
            return True
        if outcome.status == StepStatus.SKIPPED:
            self._handle_skipped(context, step, outcome)
            return False
        if is_budget_exceeded_outcome(outcome):
            self._handle_budget_exceeded(context, step, outcome)
            return False
        if outcome.status == StepStatus.BLOCKED:
            self._handle_blocked(context, step, outcome)
            return False
        self._handle_failure(context, step, outcome)
        return False

    def _handle_success(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        context.recorder.emit(
            "step_succeeded",
            {"step_id": step.step_id, "outputs": sorted(outcome.outputs.keys())},
            trace_context=context.step_trace_contexts.get(step.step_id),
        )
        self._route_after_step(context, step, outcome)

    def _handle_skipped(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        context.recorder.emit(
            "step_skipped",
            {"step_id": step.step_id, "outputs": sorted(outcome.outputs.keys())},
            trace_context=context.step_trace_contexts.get(step.step_id),
        )
        self._route_after_step(context, step, outcome)

    def _route_after_step(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        """Shared routing logic for succeeded and skipped steps."""
        try:
            routing_decision = self._routing_engine.decide(
                context.workflow,
                step,
                outcome,
                buffer=context.buffer,
                fan_out=True,
            )
        except Exception as exc:
            error = WorkflowError(
                error_type=type(exc).__name__,
                message=str(exc),
                step_id=step.step_id,
                details={"phase": "routing"},
            )
            self._commit_terminal_transition(
                context,
                WorkflowRuntimeEvent(
                    event_type=WorkflowRuntimeEventType.FAIL,
                    reason=str(exc),
                    step_id=step.step_id,
                    metadata={
                        "phase": "routing",
                        "exception": repr(exc),
                    },
                ),
                error=error,
                trace_context=context.step_trace_contexts.get(step.step_id),
            )
            context.current_step_ids = []
            return
        self._event_bridge.emit_routing_events(
            context.recorder,
            routing_decision,
            trace_context=context.step_trace_contexts.get(step.step_id),
        )
        context.current_step_ids = prepend_schedulable_steps(
            workflow=context.workflow,
            new_step_ids=routing_decision.target_step_ids,
            existing_step_ids=context.current_step_ids,
            step_results=context.step_results,
        )

    def _handle_pause(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        context.current_step_ids = [step.step_id, *context.current_step_ids]
        step_trace = context.step_trace_contexts.get(step.step_id)
        checkpoint_id = self._write_checkpoint(context, emit_event=False)
        pause_checkpoint_id = checkpoint_id or f"pause-artifact:{context.run_id}:{step.step_id}"
        compatibility_facts = [
            WorkflowEventFact(
                "step_paused",
                {"step_id": step.step_id, "outcome": outcome},
                trace_context=step_trace,
            )
        ]
        if checkpoint_id is not None:
            compatibility_facts.append(
                WorkflowEventFact(
                    "checkpoint_created",
                    checkpoint_created_payload(
                        checkpoint_id=checkpoint_id,
                        current_step_ids=context.current_step_ids,
                        path=context.path,
                    ),
                    trace_context=step_trace,
                )
            )
        if step.step_type == StepType.HUMAN_REVIEW:
            human_review_request_id = human_review_request_id_for(step, outcome)
            compatibility_facts.extend(
                [
                    WorkflowEventFact(
                        "human_review_requested",
                        {
                            "step_id": step.step_id,
                            "request_id": human_review_request_id,
                            "checkpoint_id": pause_checkpoint_id,
                        },
                        trace_context=step_trace,
                    ),
                    WorkflowEventFact(
                        "human_review_paused",
                        {"step_id": step.step_id, "outcome": outcome},
                        trace_context=step_trace,
                    ),
                    WorkflowEventFact(
                        "workflow_paused",
                        {"reason": "human_review", "step_id": step.step_id},
                        trace_context=step_trace,
                    ),
                ]
            )
            transition = WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW,
                reason="human_review_required",
                step_id=step.step_id,
                checkpoint_id=pause_checkpoint_id,
                human_review_request_id=human_review_request_id,
            )

            commit_workflow_transition(
                context=context,
                state_machine=self._state_machine,
                event=transition,
                append=lambda next_status: context.recorder.emit_batch(
                    [
                        *compatibility_facts,
                        workflow_transition_fact(
                            event=transition,
                            previous_status=context.status,
                            next_status=next_status,
                            compatibility_facts=compatibility_facts,
                            trace_context=step_trace,
                        ),
                    ]
                ),
            )
            return
        compatibility_facts.append(
            WorkflowEventFact(
                "workflow_paused",
                {"reason": "step_paused", "step_id": step.step_id},
                trace_context=step_trace,
            )
        )
        transition = WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.PAUSE,
            reason="step_paused",
            step_id=step.step_id,
            checkpoint_id=pause_checkpoint_id,
        )
        commit_workflow_transition(
            context=context,
            state_machine=self._state_machine,
            event=transition,
            append=lambda next_status: context.recorder.emit_batch(
                [
                    *compatibility_facts,
                    workflow_transition_fact(
                        event=transition,
                        previous_status=context.status,
                        next_status=next_status,
                        compatibility_facts=compatibility_facts,
                        trace_context=step_trace,
                    ),
                ]
            ),
        )

    def _handle_budget_exceeded(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        error = WorkflowError(
            error_type=outcome.error_type or "WorkflowBudgetExceeded",
            message=(
                outcome.error_message
                or f"workflow budget exceeded at step: {step.step_id}"
            ),
            step_id=step.step_id,
            details=outcome.error_details,
        )
        trace_context = context.step_trace_contexts.get(step.step_id)
        self._commit_terminal_transition(
            context,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.BUDGET_EXCEEDED,
                reason=outcome.error_message or "workflow_budget_exceeded",
                step_id=step.step_id,
                metadata=outcome.error_details,
            ),
            error=error,
            trace_context=trace_context,
            before_terminal_event=lambda: context.recorder.emit(
                "step_blocked"
                if outcome.status == StepStatus.BLOCKED
                else "step_failed",
                {"step_id": step.step_id, "outcome": outcome},
                trace_context=trace_context,
            ),
        )
        context.current_step_ids = []

    def _handle_blocked(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        error = WorkflowError(
            error_type=outcome.error_type or "StepBlocked",
            message=outcome.error_message or f"step blocked: {step.step_id}",
            step_id=step.step_id,
            details=outcome.error_details,
        )
        trace_context = context.step_trace_contexts.get(step.step_id)
        self._commit_terminal_transition(
            context,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.BLOCK,
                reason=outcome.error_message or "step_blocked",
                step_id=step.step_id,
                metadata=outcome.error_details,
            ),
            error=error,
            trace_context=trace_context,
            before_terminal_event=lambda: context.recorder.emit(
                "step_blocked",
                {"step_id": step.step_id, "outcome": outcome},
                trace_context=trace_context,
            ),
        )
        self._manifest_updater.record_policy_violation(outcome)
        context.current_step_ids = []

    def _handle_failure(
        self,
        context: WorkflowExecutionContext,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        context.recorder.emit(
            "step_failed",
            {"step_id": step.step_id, "outcome": outcome},
            trace_context=context.step_trace_contexts.get(step.step_id),
        )
        step_error = WorkflowError(
            error_type=outcome.error_type or "StepFailed",
            message=outcome.error_message or f"step failed: {step.step_id}",
            step_id=step.step_id,
            details=outcome.error_details,
        )
        if blocks_on_failure(step):
            trace_context = context.step_trace_contexts.get(step.step_id)
            self._commit_terminal_transition(
                context,
                WorkflowRuntimeEvent(
                    event_type=WorkflowRuntimeEventType.BLOCK,
                    reason=step_error.message,
                    step_id=step.step_id,
                    metadata=step_error.details,
                ),
                error=step_error,
                trace_context=trace_context,
                before_terminal_event=lambda: context.recorder.emit(
                    "step_blocked",
                    {"step_id": step.step_id, "outcome": outcome},
                    trace_context=trace_context,
                ),
            )
            self._manifest_updater.record_policy_violation(outcome)
            context.current_step_ids = []
            return
        fallback_step_id = failure_fallback_step_id(context.workflow, step)
        if fallback_step_id is not None:
            context.current_step_ids = prepend_new_steps(
                [fallback_step_id],
                context.current_step_ids,
            )
            return
        self._commit_terminal_transition(
            context,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.FAIL,
                reason=step_error.message,
                step_id=step.step_id,
                metadata=step_error.details,
            ),
            error=step_error,
            trace_context=context.step_trace_contexts.get(step.step_id),
        )
        context.current_step_ids = []

    def _write_checkpoint(
        self,
        context: WorkflowExecutionContext,
        *,
        emit_event: bool = True,
    ) -> str | None:
        return self._checkpoint_coordinator.write_checkpoint(
            run_id=context.run_id,
            workflow=context.workflow,
            profile=context.profile,
            current_step_ids=context.current_step_ids,
            buffer=context.buffer,
            step_results=context.step_results,
            path=context.path,
            recorder=context.recorder,
            manifest=context.manifest,
            checkpoint_ids=context.checkpoint_ids,
            execution_limits=context.execution_limits,
            trace_context=(
                context.step_trace_contexts.get(context.path[-1])
                if context.path
                else context.trace_context
            ),
            emit_event=emit_event,
        )


def blocks_on_failure(step: StepSpec) -> bool:
    policy = step.failure_policy
    return policy.mark_as_blocked or policy.on_failure == "mark_as_blocked"


def failure_fallback_step_id(workflow: WorkflowSpec, step: StepSpec) -> str | None:
    if step.failure_policy.fallback_step_id is not None:
        return step.failure_policy.fallback_step_id
    edges = [
        edge
        for edge in workflow.edges
        if edge.source_step_id == step.step_id and edge.condition == EdgeCondition.ON_FAILURE
    ]
    edges.sort(key=lambda edge: (edge.priority, edge.edge_id))
    if not edges:
        return None
    return edges[0].target_step_id


def commit_workflow_transition(
    *,
    context: WorkflowExecutionContext,
    state_machine: WorkflowStateMachine,
    event: WorkflowRuntimeEvent,
    append: Callable[[WorkflowStatus], Any],
) -> WorkflowStatus:
    """Commit the durable transition fact before advancing local workflow state."""

    next_status = state_machine.transition(context.status, event)
    append(next_status)
    context.status = next_status
    return next_status


def workflow_transition_fact(
    *,
    event: WorkflowRuntimeEvent,
    previous_status: WorkflowStatus,
    next_status: WorkflowStatus,
    compatibility_facts: list[WorkflowEventFact],
    trace_context: TraceContext | None,
) -> WorkflowEventFact:
    return WorkflowEventFact(
        "workflow_transition_committed",
        {
            "transition_type": event.event_type.value,
            "previous_status": previous_status.value,
            "next_status": next_status.value,
            "reason": event.reason or event.event_type.value,
            "checkpoint_step_id": event.step_id,
            "checkpoint_id": event.checkpoint_id,
            "human_review_request_id": event.human_review_request_id,
            "compatibility_event_types": [
                fact.event_type for fact in compatibility_facts
            ],
        },
        trace_context=trace_context,
    )


def human_review_request_id_for(step: StepSpec, outcome: StepOutcome) -> str:
    request_key = str(step.metadata.get("request_key") or "human_review_request")
    request = outcome.outputs.get(request_key)
    for source in (
        request,
        outcome.outputs.get("human_review_request"),
        outcome.outputs.get("human_review_decision"),
    ):
        request_id = field_value(source, "request_id") or field_value(source, "id")
        if request_id is not None:
            return str(request_id)
    return f"{step.step_id}:human_review_request"


def field_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    return None


def prepend_new_steps(new_step_ids: list[str], existing_step_ids: list[str]) -> list[str]:
    # O(n) fix: set lookup + list concat replaces O(n²) insert-at-front loop
    existing_set = set(existing_step_ids)
    to_add = [s for s in new_step_ids if s not in existing_set]
    return to_add + list(existing_step_ids)


def prepend_schedulable_steps(
    *,
    workflow: WorkflowSpec,
    new_step_ids: list[str],
    existing_step_ids: list[str],
    step_results: dict[str, StepOutcome],
) -> list[str]:
    schedulable = [
        step_id
        for step_id in new_step_ids
        if should_schedule_join(
            workflow=workflow,
            join_step=workflow.step_by_id(step_id),
            step_results=step_results,
        )
    ]
    return prepend_new_steps(schedulable, existing_step_ids)


def should_schedule_join(
    *,
    workflow: WorkflowSpec,
    join_step: StepSpec,
    step_results: dict[str, StepOutcome],
) -> bool:
    if join_step.step_type != StepType.JOIN:
        return True
    required_upstream_step_ids = join_required_upstream_step_ids(workflow, join_step)
    if not required_upstream_step_ids:
        return True
    return all(
        step_id in step_results and is_terminal_step_outcome(step_results[step_id])
        for step_id in required_upstream_step_ids
    )


def join_required_upstream_step_ids(workflow: WorkflowSpec, join_step: StepSpec) -> list[str]:
    raw = join_step.metadata.get("required_upstream_step_ids") or join_step.metadata.get("upstream_step_ids")
    if isinstance(raw, list) and raw:
        return [str(step_id) for step_id in raw]
    return [
        edge.source_step_id
        for edge in workflow.edges
        if edge.target_step_id == join_step.step_id
    ]


def is_terminal_step_outcome(outcome: StepOutcome) -> bool:
    return outcome.status in {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.BLOCKED,
        StepStatus.SKIPPED,
        StepStatus.TIMEOUT,
        StepStatus.CANCELLED,
    }
