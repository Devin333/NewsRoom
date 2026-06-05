from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from typing import Any, Callable

from framework.specs import StepSpec, StepStatus
from framework.events.trace import TraceContext
from framework.shared.time import utc_now
from framework.workflow.buffer import DataBuffer
from framework.workflow.governance.resource import StepResourceEstimator, StepResourceGuard
from framework.workflow.governance.safety import safety_violation_for_step
from framework.events import EventRecorder
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.base import StepExecutionError, StepRunnerResolutionError
from framework.workflow.runners.registry import StepRunnerRegistry

WORKFLOW_STEP_TIMEOUT_ERROR = "WorkflowStepTimeoutError"


class StepInvoker:
    def __init__(
        self,
        *,
        step_runner_registry: StepRunnerRegistry,
        sleep_fn: Callable[[float], None],
    ) -> None:
        self._step_runner_registry = step_runner_registry
        self._sleep_fn = sleep_fn

    def run_step_with_retries(
        self,
        step: StepSpec,
        buffer: DataBuffer,
        recorder: EventRecorder,
        *,
        trace_context: TraceContext | None = None,
    ) -> StepOutcome:
        retry_policy = step.retry_policy
        max_attempts = retry_policy.max_retries + 1
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
            scoped_buffer = buffer.scoped(step.step_id)
            self._configure_runner_trace_context(step, trace_context)
            outcome = standardize_step_outcome(
                self._run_step_attempt(step, scoped_buffer, attempt, max_attempts),
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
                        "on_timeout": step.timeout_policy.on_timeout,
                    },
                    trace_context=trace_context,
                )
            if not is_retryable_outcome(step, outcome):
                return outcome
            if attempt >= max_attempts or not retry_policy.should_retry(
                error_type=outcome.error_type
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
        scoped_buffer: Any,
        attempt: int,
        max_attempts: int,
    ) -> StepOutcome:
        timeout_seconds = step.timeout_policy.timeout_seconds
        if timeout_seconds is None:
            return self._invoke_step_runner(step, scoped_buffer, attempt, max_attempts)

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-workflow-step")
        future = pool.submit(
            self._invoke_step_runner,
            step,
            scoped_buffer,
            attempt,
            max_attempts,
        )
        timed_out = False
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            timed_out = True
            future.cancel()
            return StepOutcome(
                status=StepStatus.TIMEOUT,
                error_type=WORKFLOW_STEP_TIMEOUT_ERROR,
                error_message=(
                    f"step {step.step_id} exceeded timeout of {timeout_seconds:g} seconds"
                ),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "timeout_seconds": timeout_seconds,
                    "on_timeout": step.timeout_policy.on_timeout,
                },
            )
        finally:
            pool.shutdown(wait=not timed_out, cancel_futures=True)

    def _invoke_step_runner(
        self,
        step: StepSpec,
        scoped_buffer: Any,
        attempt: int,
        max_attempts: int,
    ) -> StepOutcome:
        try:
            runner = self._step_runner_registry.resolve(step)
            if runner is None:
                raise StepRunnerResolutionError(
                    "step runner cannot resolve step: "
                    f"{step.step_id} ({step.step_type.value}:{step.implementation})"
                )
            outcome = runner.run(step, scoped_buffer)
            if not isinstance(outcome, StepOutcome):
                raise StepExecutionError(
                    f"step runner returned {type(outcome).__name__}, expected StepOutcome"
                )
            return outcome_with_attempt(outcome, attempt=attempt, max_attempts=max_attempts)
        except Exception as exc:  # pragma: no cover - concrete branches covered by tests
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_details={"attempt": attempt, "max_attempts": max_attempts},
            )


def is_retryable_outcome(step: StepSpec, outcome: StepOutcome) -> bool:
    if is_budget_exceeded_outcome(outcome):
        return False
    if outcome.status == StepStatus.FAILED:
        return True
    if outcome.status == StepStatus.TIMEOUT:
        return step.timeout_policy.on_timeout == "retry"
    return False


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
