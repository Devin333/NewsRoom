from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from framework.specs import StepSpec, StepStatus
from framework.events.trace import TraceContext
from framework.shared.attempts import (
    AttemptBudget,
    AttemptBudgetExhaustedError,
    AttemptCancelledError,
    AttemptContext,
    AttemptState,
    AttemptSupervisor,
    current_attempt_context,
)
from framework.shared.time import utc_now
from framework.workflow.buffer import (
    AttemptDataBufferOverlay,
    DataBuffer,
    StaleWorkflowAttemptError,
)
from framework.workflow.governance.resource import StepResourceEstimator, StepResourceGuard
from framework.workflow.governance.safety import safety_violation_for_step
from framework.workflow.runtime.event_emitter import WorkflowEventRecorder
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerResolutionError,
    StepRunnerSideEffectLevel,
)
from framework.workflow.runners.registry import StepRunnerRegistry

WORKFLOW_STEP_TIMEOUT_ERROR = "WorkflowStepTimeoutError"
WORKFLOW_STEP_INDETERMINATE_TIMEOUT_ERROR = (
    "WorkflowStepIndeterminateTimeoutError"
)


class StepInvoker:
    def __init__(
        self,
        *,
        step_runner_registry: StepRunnerRegistry,
        sleep_fn: Callable[[float], None],
        cancellation_grace_seconds: float = 0.1,
    ) -> None:
        if cancellation_grace_seconds < 0:
            raise ValueError("cancellation_grace_seconds must be non-negative")
        self._step_runner_registry = step_runner_registry
        self._sleep_fn = sleep_fn
        self._cancellation_grace_seconds = float(cancellation_grace_seconds)

    def run_step_with_retries(
        self,
        step: StepSpec,
        buffer: DataBuffer,
        recorder: WorkflowEventRecorder,
        *,
        trace_context: TraceContext | None = None,
    ) -> StepOutcome:
        retry_policy = step.retry_policy
        max_attempts = retry_policy.max_attempts or (retry_policy.max_retries + 1)
        budget = AttemptBudget(max_attempts=max_attempts)
        idempotency_key = _step_idempotency_key(step, trace_context)
        attempt = 1
        while True:
            attempt_started_at = utc_now()
            recorder.emit(
                "step_started",
                {
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
                trace_context=trace_context,
            )
            resource_violation = resource_policy_violation(step, buffer)
            if resource_violation is not None:
                recorder.emit("policy_violation", resource_violation, trace_context=trace_context)
                return standardize_step_outcome(
                    StepOutcome(
                        status=StepStatus.BLOCKED,
                        error_type="WorkflowResourcePolicyViolation",
                        error_message=resource_violation["message"],
                        error_details=resource_violation,
                    ),
                    step=step,
                    trace_context=trace_context,
                    started_at=attempt_started_at,
                )
            safety_violation = safety_violation_for_step(step)
            if safety_violation is not None:
                recorder.emit(
                    "runtime_safety_violation",
                    safety_violation,
                    trace_context=trace_context,
                )
                return standardize_step_outcome(
                    StepOutcome(
                        status=StepStatus.BLOCKED,
                        error_type="WorkflowRuntimeSafetyViolation",
                        error_message=safety_violation["message"],
                        error_details=safety_violation,
                    ),
                    step=step,
                    trace_context=trace_context,
                    started_at=attempt_started_at,
                )
            capability_violation = step_runner_capability_violation(
                step,
                self._step_runner_registry,
                resume_mode=False,
            )
            if capability_violation is not None:
                recorder.emit(
                    "runner_capability_violation",
                    capability_violation,
                    trace_context=trace_context,
                )
                return standardize_step_outcome(
                    StepOutcome(
                        status=StepStatus.FAILED,
                        error_type="StepRunnerCapabilityError",
                        error_message=capability_violation["message"],
                        error_details=capability_violation,
                    ),
                    step=step,
                    trace_context=trace_context,
                    started_at=attempt_started_at,
                )
            try:
                fencing_token = budget.claim()
            except AttemptBudgetExhaustedError:
                return standardize_step_outcome(
                    StepOutcome(
                        status=StepStatus.FAILED,
                        error_type="AttemptBudgetExhaustedError",
                        error_message="step attempt budget exhausted",
                        error_details={
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "budget_exceeded": True,
                        },
                    ),
                    step=step,
                    trace_context=trace_context,
                    started_at=attempt_started_at,
                )
            attempt_buffer = buffer.begin_attempt(step.step_id, fencing_token)
            self._configure_runner_trace_context(step, trace_context)
            outcome = standardize_step_outcome(
                self._run_step_attempt(
                    step,
                    attempt_buffer,
                    attempt,
                    max_attempts,
                    budget=budget,
                    idempotency_key=idempotency_key,
                    fencing_token=fencing_token,
                ),
                step=step,
                trace_context=trace_context,
                started_at=attempt_started_at,
            )
            if outcome.status == StepStatus.TIMEOUT:
                recorder.emit(
                    "step_timeout",
                    {
                        "step_id": step.step_id,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "timeout_seconds": step.timeout_policy.timeout_seconds,
                        "configured_timeout_seconds": outcome.error_details.get(
                            "configured_timeout_seconds"
                        ),
                        "effective_timeout_seconds": outcome.error_details.get(
                            "effective_timeout_seconds"
                        ),
                        "cancellation_source": outcome.error_details.get(
                            "cancellation_source"
                        ),
                        "on_timeout": step.timeout_policy.on_timeout,
                        "termination_confirmed": outcome.error_details.get(
                            "termination_confirmed"
                        ),
                        "indeterminate": outcome.error_details.get(
                            "indeterminate",
                            False,
                        ),
                    },
                    trace_context=trace_context,
                )
            if not is_retryable_outcome(
                step,
                outcome,
                registry=self._step_runner_registry,
            ):
                return outcome
            if (
                attempt >= max_attempts
                or budget.remaining <= 0
                or not retry_policy.should_retry(
                    error_type=outcome.error_type
                )
            ):
                return outcome

            retry_index = attempt
            delay_seconds = retry_policy.delay_for_retry(retry_index)
            recorder.emit(
                "step_retry_scheduled",
                {
                    "step_id": step.step_id,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "error_type": outcome.error_type,
                    "error_message": outcome.error_message,
                    "delay_seconds": delay_seconds,
                },
                trace_context=trace_context,
            )
            if delay_seconds:
                self._sleep_fn(delay_seconds)
            attempt += 1

    def _configure_runner_trace_context(
        self,
        step: StepSpec,
        trace_context: TraceContext | None,
    ) -> None:
        if trace_context is None:
            return
        runner = self._step_runner_registry.resolve(step)
        if runner is None:
            return
        configure_trace = getattr(runner, "configure_trace_context", None)
        if callable(configure_trace):
            configure_trace(trace_context=trace_context)
        configure_step_context = getattr(runner, "configure_step_context", None)
        if callable(configure_step_context):
            configure_step_context(trace_context=trace_context)

    def _run_step_attempt(
        self,
        step: StepSpec,
        attempt_buffer: AttemptDataBufferOverlay,
        attempt: int,
        max_attempts: int,
        *,
        budget: AttemptBudget,
        idempotency_key: str,
        fencing_token: int,
    ) -> StepOutcome:
        timeout_seconds = step.timeout_policy.timeout_seconds
        try:
            grace_seconds = float(
                step.metadata.get(
                    "cancellation_grace_seconds",
                    self._cancellation_grace_seconds,
                )
            )
        except (TypeError, ValueError):
            attempt_buffer.close()
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type="StepExecutionError",
                error_message="cancellation_grace_seconds must be numeric",
            )
        if grace_seconds < 0:
            attempt_buffer.close()
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type="StepExecutionError",
                error_message="cancellation_grace_seconds must be non-negative",
            )
        supervisor = AttemptSupervisor(
            cancellation_grace_seconds=grace_seconds
        )
        parent_context = current_attempt_context()
        effective_timeout = timeout_seconds
        cancellation_source = "step_deadline"
        if parent_context is not None and parent_context.remaining_seconds is not None:
            if effective_timeout is None:
                effective_timeout = parent_context.remaining_seconds
                cancellation_source = "parent_attempt"
            else:
                if parent_context.remaining_seconds <= float(effective_timeout):
                    cancellation_source = "parent_attempt"
                effective_timeout = min(
                    float(effective_timeout),
                    parent_context.remaining_seconds,
                )
        supervised = supervisor.run(
            lambda: self._invoke_step_runner(
                step,
                attempt_buffer,
                attempt,
                max_attempts,
            ),
            timeout_seconds=effective_timeout,
            idempotency_key=idempotency_key,
            fencing_token=fencing_token,
            budget=budget,
            parent_cancel_event=(
                parent_context.cancel_event
                if parent_context is not None
                else None
            ),
            parent_context=parent_context,
            claim_budget=False,
        )
        if supervised.state is AttemptState.TIMED_OUT:
            attempt_buffer.close()
            indeterminate = (
                supervised.indeterminate
                or not _timeout_retry_is_safe(
                    step,
                    self._step_runner_registry,
                )
            )
            if parent_context is not None:
                if not supervised.termination_confirmed:
                    parent_context.mark_descendant_unconfirmed()
                elif indeterminate:
                    parent_context.mark_descendant_indeterminate()
            return StepOutcome(
                status=StepStatus.TIMEOUT,
                error_type=(
                    WORKFLOW_STEP_INDETERMINATE_TIMEOUT_ERROR
                    if indeterminate
                    else WORKFLOW_STEP_TIMEOUT_ERROR
                ),
                error_message=(
                    f"step {step.step_id} exceeded its configured timeout"
                ),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "timeout_seconds": timeout_seconds,
                    "configured_timeout_seconds": timeout_seconds,
                    "effective_timeout_seconds": effective_timeout,
                    "cancellation_source": cancellation_source,
                    "on_timeout": step.timeout_policy.on_timeout,
                    "attempt_id": supervised.context.attempt_id,
                    "idempotency_key": supervised.context.idempotency_key,
                    "fencing_token": supervised.context.fencing_token,
                    "termination_confirmed": supervised.termination_confirmed,
                    "indeterminate": indeterminate,
                },
            )
        if supervised.state is AttemptState.FAILED:
            attempt_buffer.close()
            error = supervised.error
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=(type(error).__name__ if error is not None else "StepExecutionError"),
                error_message=(str(error) if error is not None else "step attempt failed"),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "attempt_id": supervised.context.attempt_id,
                    "idempotency_key": supervised.context.idempotency_key,
                    "fencing_token": supervised.context.fencing_token,
                },
            )

        outcome = supervised.value
        if not isinstance(outcome, StepOutcome):
            attempt_buffer.close()
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type="StepExecutionError",
                error_message="step attempt returned an invalid outcome",
            )
        if parent_context is not None and parent_context.cancelled:
            attempt_buffer.close()
            indeterminate = not _timeout_retry_is_safe(
                step,
                self._step_runner_registry,
            )
            return StepOutcome(
                status=StepStatus.TIMEOUT,
                error_type=(
                    WORKFLOW_STEP_INDETERMINATE_TIMEOUT_ERROR
                    if indeterminate
                    else WORKFLOW_STEP_TIMEOUT_ERROR
                ),
                error_message=f"step {step.step_id} was cancelled by its parent attempt",
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "attempt_id": supervised.context.attempt_id,
                    "idempotency_key": supervised.context.idempotency_key,
                    "fencing_token": supervised.context.fencing_token,
                    "termination_confirmed": True,
                    "indeterminate": indeterminate,
                    "configured_timeout_seconds": timeout_seconds,
                    "effective_timeout_seconds": effective_timeout,
                    "cancellation_source": "parent_attempt",
                },
            )
        outcome = _with_attempt_context(outcome, supervised.context)
        if outcome.status in {StepStatus.SUCCEEDED, StepStatus.PAUSED}:
            try:
                attempt_buffer.commit()
            except StaleWorkflowAttemptError as exc:
                return StepOutcome(
                    status=StepStatus.FAILED,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    error_details=dict(outcome.error_details),
                )
        else:
            attempt_buffer.close()
        return outcome

    def _invoke_step_runner(
        self,
        step: StepSpec,
        scoped_buffer: Any,
        attempt: int,
        max_attempts: int,
    ) -> StepOutcome:
        try:
            context = current_attempt_context()
            if context is not None:
                context.raise_if_cancelled()
            runner = self._step_runner_registry.resolve(step)
            if runner is None:
                raise StepRunnerResolutionError(
                    "step runner cannot resolve step: "
                    f"{step.step_id} ({step.step_type.value}:{step.implementation})"
                )
            outcome = runner.run(step, scoped_buffer)
            if context is not None:
                context.raise_if_cancelled()
            if not isinstance(outcome, StepOutcome):
                raise StepExecutionError(
                    f"step runner returned {type(outcome).__name__}, expected StepOutcome"
                )
            return outcome_with_attempt(outcome, attempt=attempt, max_attempts=max_attempts)
        except AttemptCancelledError:
            raise
        except Exception as exc:  # pragma: no cover - concrete branches covered by tests
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_details={"attempt": attempt, "max_attempts": max_attempts},
            )


def is_retryable_outcome(
    step: StepSpec,
    outcome: StepOutcome,
    *,
    registry: StepRunnerRegistry | None = None,
) -> bool:
    if is_budget_exceeded_outcome(outcome):
        return False
    if outcome.status == StepStatus.FAILED:
        return True
    if outcome.status == StepStatus.TIMEOUT:
        if step.timeout_policy.on_timeout != "retry":
            return False
        if outcome.error_details.get("termination_confirmed") is False:
            return False
        if outcome.error_details.get("indeterminate") is True:
            return False
        return registry is None or _timeout_retry_is_safe(step, registry)
    return False


def _step_idempotency_key(
    step: StepSpec,
    trace_context: TraceContext | None,
) -> str:
    parent = current_attempt_context()
    if parent is not None:
        return f"{parent.idempotency_key}:step:{step.step_id}"
    configured = step.metadata.get("idempotency_key")
    if configured:
        return str(configured)
    trace_id = trace_context.trace_id if trace_context is not None else "local"
    return f"workflow-step:{trace_id}:{step.step_id}"


def _timeout_retry_is_safe(
    step: StepSpec,
    registry: StepRunnerRegistry,
) -> bool:
    runner = registry.resolve(step)
    capability = getattr(runner, "capability", None)
    if capability is None:
        return False
    side_effect_level = StepRunnerSideEffectLevel(capability.side_effect_level)
    if side_effect_level in {
        StepRunnerSideEffectLevel.NONE,
        StepRunnerSideEffectLevel.READ_ONLY,
    }:
        return True
    if side_effect_level is StepRunnerSideEffectLevel.IDEMPOTENT_WRITE:
        return bool(step.idempotent)
    return bool(
        step.metadata.get("idempotency_contract") is True
        and step.metadata.get("reconciliation_supported") is True
    )


def _with_attempt_context(
    outcome: StepOutcome,
    context: AttemptContext,
) -> StepOutcome:
    error_details = dict(outcome.error_details)
    metrics = dict(outcome.metrics)
    metadata = dict(outcome.metadata)
    attempt_metadata = {
        "attempt_id": context.attempt_id,
        "idempotency_key": context.idempotency_key,
        "fencing_token": context.fencing_token,
    }
    if outcome.status in {
        StepStatus.FAILED,
        StepStatus.BLOCKED,
        StepStatus.TIMEOUT,
    }:
        for key, value in attempt_metadata.items():
            error_details.setdefault(key, value)
    for key, value in attempt_metadata.items():
        metrics.setdefault(key, value)
        metadata.setdefault(key, value)
    return replace(
        outcome,
        error_details=error_details,
        metrics=metrics,
        metadata=metadata,
    )


def is_budget_exceeded_outcome(outcome: StepOutcome) -> bool:
    if outcome.status not in {StepStatus.FAILED, StepStatus.BLOCKED, StepStatus.TIMEOUT}:
        return False
    if outcome.outputs.get("budget_exceeded") is True:
        return True
    if outcome.error_details.get("budget_exceeded") is True:
        return True
    error_type = str(outcome.error_type or "").casefold()
    return "budget" in error_type and "exceed" in error_type


def outcome_with_attempt(outcome: StepOutcome, *, attempt: int, max_attempts: int) -> StepOutcome:
    metrics = dict(outcome.metrics)
    metrics.setdefault("attempt", attempt)
    metrics.setdefault("max_attempts", max_attempts)
    error_details = dict(outcome.error_details)
    if outcome.status in {StepStatus.FAILED, StepStatus.TIMEOUT, StepStatus.BLOCKED}:
        error_details.setdefault("attempt", attempt)
        error_details.setdefault("max_attempts", max_attempts)
    return replace(outcome, error_details=error_details, metrics=metrics)


def standardize_step_outcome(
    outcome: StepOutcome,
    *,
    step: StepSpec,
    trace_context: TraceContext | None,
    started_at: Any,
) -> StepOutcome:
    completed_at = outcome.completed_at or utc_now()
    duration_value = outcome.duration_ms
    metric_duration = outcome.metrics.get("duration_ms")
    if duration_value is None and isinstance(metric_duration, (int, float)):
        duration_value = metric_duration
    if duration_value is None:
        duration_value = round((completed_at - started_at).total_seconds() * 1000, 3)
    metadata = dict(outcome.metadata)
    metadata.setdefault("step_type", step.step_type.value)
    if step.implementation is not None:
        metadata.setdefault("implementation", step.implementation)
    return replace(
        outcome,
        step_id=outcome.step_id or step.step_id,
        trace_id=outcome.trace_id or (trace_context.trace_id if trace_context else None),
        span_id=outcome.span_id or (trace_context.span_id if trace_context else None),
        started_at=outcome.started_at or started_at,
        completed_at=completed_at,
        duration_ms=duration_value,
        metadata=metadata,
    )


def resource_policy_violation(step: StepSpec, buffer: DataBuffer) -> dict[str, Any] | None:
    estimate = StepResourceEstimator().estimate_inputs(step, buffer)
    violations = StepResourceGuard().check(step, estimate)
    if not violations:
        return None
    violation = violations[0]
    payload = violation.to_dict()
    payload["policy"] = violation.code
    payload["resource_estimate"] = estimate.to_dict()
    if violation.code == "resource.max_items":
        payload["item_count"] = int(violation.actual)
        payload["max_items"] = int(violation.limit)
    return payload


def step_runner_capability_violation(
    step: StepSpec,
    registry: StepRunnerRegistry,
    *,
    resume_mode: bool,
) -> dict[str, Any] | None:
    runner = registry.resolve(step)
    if runner is None:
        return {
            "step_id": step.step_id,
            "step_type": step.step_type.value,
            "implementation": step.implementation,
            "message": (
                "No StepRunner can resolve step "
                f"{step.step_id}: {step.step_type.value}/{step.implementation}"
            ),
        }
    capability = getattr(runner, "capability", None)
    if capability is None:
        return None
    if step.timeout_policy.timeout_seconds is not None and not capability.supports_timeout:
        return {
            "step_id": step.step_id,
            "runner_id": capability.runner_id,
            "capability": "timeout",
            "message": (
                f"Runner {capability.runner_id} does not support timeout "
                f"for step {step.step_id}."
            ),
        }
    if step.retry_policy.max_retries > 0 and not capability.supports_retry:
        return {
            "step_id": step.step_id,
            "runner_id": capability.runner_id,
            "capability": "retry",
            "message": (
                f"Runner {capability.runner_id} does not support retry "
                f"for step {step.step_id}."
            ),
        }
    if resume_mode and not capability.supports_resume:
        return {
            "step_id": step.step_id,
            "runner_id": capability.runner_id,
            "capability": "resume",
            "message": (
                f"Runner {capability.runner_id} does not support resume "
                f"for step {step.step_id}."
            ),
        }
    return None
