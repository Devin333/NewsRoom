from __future__ import annotations

from dataclasses import replace
import time
from typing import Any, Callable

from framework.specs import StepSpec, StepStatus
from framework.events.trace import TraceContext
from framework.shared.attempts import (
    AttemptCancelledError,
    AttemptContext,
    AttemptFinalization,
    AttemptIdentity,
    AttemptOutcome,
    AttemptState,
    AttemptSupervisor,
    DeadlineAdmissionPolicy,
    ExecutionLimits,
    LocalRetryBudget,
    RetryCreditLedger,
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
from framework.workflow.runtime.attempt_event_sink import WorkflowDurableAttemptSink
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
WORKFLOW_STEP_INDETERMINATE_ERROR = "WorkflowStepIndeterminateError"


class StepInvoker:
    def __init__(
        self,
        *,
        step_runner_registry: StepRunnerRegistry,
        sleep_fn: Callable[[float], None],
        cancellation_grace_seconds: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cancellation_grace_seconds < 0:
            raise ValueError("cancellation_grace_seconds must be non-negative")
        self._step_runner_registry = step_runner_registry
        self._sleep_fn = sleep_fn
        self._cancellation_grace_seconds = float(cancellation_grace_seconds)
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._clock = clock

    def set_clock(self, clock: Callable[[], float]) -> None:
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._clock = clock

    def run_step_with_retries(
        self,
        step: StepSpec,
        buffer: DataBuffer,
        recorder: WorkflowEventRecorder,
        *,
        trace_context: TraceContext | None = None,
        execution_limits: ExecutionLimits | None = None,
    ) -> StepOutcome:
        retry_policy = step.retry_policy
        max_attempts = retry_policy.max_attempts or (retry_policy.max_retries + 1)
        parent_context = current_attempt_context()
        limits = execution_limits or (
            parent_context.execution_limits
            if parent_context is not None
            else None
        )
        if limits is None:
            limits = ExecutionLimits(
                retry_credits=RetryCreditLedger(
                    max_total_retries=max(0, max_attempts - 1)
                )
            )
        local_budget = LocalRetryBudget(max_attempts=max_attempts)
        idempotency_key = _step_idempotency_key(step, trace_context)

        preflight_started_at = utc_now()
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
                started_at=preflight_started_at,
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
                started_at=preflight_started_at,
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
                started_at=preflight_started_at,
            )

        while True:
            attempt = local_budget.used + 1
            attempt_started_at = utc_now()
            self._configure_runner_trace_context(step, trace_context)
            outcome = standardize_step_outcome(
                self._run_step_attempt(
                    step,
                    buffer,
                    attempt,
                    max_attempts,
                    local_budget=local_budget,
                    execution_limits=limits,
                    idempotency_key=idempotency_key,
                    recorder=recorder,
                    trace_context=trace_context,
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
        buffer: DataBuffer,
        attempt: int,
        max_attempts: int,
        *,
        local_budget: LocalRetryBudget,
        execution_limits: ExecutionLimits,
        idempotency_key: str,
        recorder: WorkflowEventRecorder,
        trace_context: TraceContext | None,
    ) -> StepOutcome:
        timeout_seconds = step.timeout_policy.timeout_seconds
        grace_seconds = (
            step.timeout_policy.cancellation_grace_seconds
            if step.timeout_policy.cancellation_grace_seconds is not None
            else self._cancellation_grace_seconds
        )
        supervisor = AttemptSupervisor(
            cancellation_grace_seconds=grace_seconds,
            clock=self._clock,
        )
        parent_context = current_attempt_context()
        attempt_buffer_holder: dict[str, AttemptDataBufferOverlay] = {}

        def prepare(identity: AttemptIdentity) -> Callable[[], None]:
            attempt_buffer = buffer.begin_attempt(
                step.step_id,
                owner_id=identity.attempt_id,
            )
            attempt_buffer_holder["value"] = attempt_buffer

            def cleanup() -> None:
                attempt_buffer.close()
                abandon = getattr(buffer, "abandon_attempt", None)
                if callable(abandon):
                    abandon(
                        step.step_id,
                        lease_generation=attempt_buffer.fencing_token,
                        owner_id=identity.attempt_id,
                    )

            return cleanup

        def invoke_started_attempt() -> StepOutcome:
            context = current_attempt_context()
            if context is None:
                raise RuntimeError("workflow step is missing attempt context")
            recorder.emit(
                "step_started",
                {
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "attempt": context.local_attempt_no,
                    "max_attempts": max_attempts,
                },
                trace_context=trace_context,
            )
            return self._invoke_step_runner(
                step,
                attempt_buffer_holder["value"],
                context.local_attempt_no,
                max_attempts,
            )

        def finalize_attempt(
            outcome: AttemptOutcome[StepOutcome],
        ) -> AttemptOutcome[StepOutcome] | AttemptFinalization[StepOutcome]:
            context = outcome.context
            if context is None:
                raise RuntimeError("workflow step is missing attempt context")
            if outcome.state is not AttemptState.SUCCEEDED:
                return outcome
            step_outcome = outcome.value
            if not isinstance(step_outcome, StepOutcome):
                return replace(
                    outcome,
                    state=AttemptState.FAILED,
                    value=None,
                    error=StepExecutionError(
                        "step attempt returned an invalid outcome"
                    ),
                )
            step_outcome = _with_attempt_context(step_outcome, context)
            if step_outcome.status in {StepStatus.SUCCEEDED, StepStatus.PAUSED}:
                try:
                    context.raise_if_cancelled()
                    context.raise_if_indeterminate()
                    transaction = attempt_buffer_holder["value"].begin_commit()
                except AttemptCancelledError as exc:
                    return replace(
                        outcome,
                        state=AttemptState.TIMED_OUT,
                        value=None,
                        error=exc,
                        timed_out=True,
                        termination_confirmed=True,
                        reason_code=exc.code,
                    )
                except StaleWorkflowAttemptError as exc:
                    return replace(
                        outcome,
                        state=AttemptState.FAILED,
                        value=None,
                        error=exc,
                        reason_code=type(exc).__name__,
                    )
                return AttemptFinalization(
                    outcome=replace(outcome, value=step_outcome),
                    rollback=transaction.rollback,
                    complete=transaction.complete,
                )
            if step_outcome.status in {StepStatus.FAILED, StepStatus.BLOCKED}:
                error = StepExecutionError(
                    step_outcome.error_message
                    or f"step {step.step_id} returned {step_outcome.status.value}"
                )
                indeterminate = bool(
                    step_outcome.error_details.get("indeterminate", False)
                    or (
                        step_outcome.status is StepStatus.FAILED
                        and not _retry_is_safe(step, self._step_runner_registry)
                        and not _step_outcome_has_confirmed_determinate_effect(
                            step_outcome
                        )
                        and not _step_outcome_failure_is_known_to_have_no_effect(
                            step,
                            step_outcome,
                        )
                    )
                )
                return replace(
                    outcome,
                    state=(
                        AttemptState.INDETERMINATE
                        if indeterminate
                        else AttemptState.FAILED
                    ),
                    value=step_outcome,
                    error=error,
                    indeterminate=indeterminate,
                    reason_code=(
                        WORKFLOW_STEP_INDETERMINATE_ERROR
                        if indeterminate
                        else step_outcome.error_type or type(error).__name__
                    ),
                )
            if step_outcome.status in {StepStatus.TIMEOUT, StepStatus.CANCELLED}:
                error = AttemptCancelledError(context.attempt_id)
                return replace(
                    outcome,
                    state=AttemptState.TIMED_OUT,
                    value=step_outcome,
                    error=error,
                    timed_out=True,
                    indeterminate=bool(
                        step_outcome.error_details.get("indeterminate", False)
                    ),
                    reason_code=step_outcome.error_type or error.code,
                )
            if step_outcome.status is StepStatus.SKIPPED:
                return replace(outcome, value=step_outcome)
            return replace(
                outcome,
                state=AttemptState.FAILED,
                value=step_outcome,
                error=StepExecutionError(
                    f"step {step.step_id} returned non-terminal status "
                    f"{step_outcome.status.value}"
                ),
                reason_code="step_non_terminal_outcome",
            )

        supervised = supervisor.run(
            invoke_started_attempt,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            operation_id=idempotency_key,
            operation_kind="workflow_step",
            local_budget=local_budget,
            execution_limits=execution_limits,
            admission_policy=DeadlineAdmissionPolicy(
                timeout_seconds=timeout_seconds,
                min_start_window_seconds=(
                    step.timeout_policy.min_start_window_seconds
                ),
                cancellation_grace_seconds=grace_seconds,
                completion_reserve_seconds=(
                    step.timeout_policy.completion_reserve_seconds
                ),
            ),
            parent_context=parent_context,
            prepare=prepare,
            finalize=finalize_attempt,
            event_sink=WorkflowDurableAttemptSink(
                recorder=recorder,
                execution_id=execution_limits.execution_id,
                trace_context=trace_context,
            ),
        )
        if supervised.state is AttemptState.REJECTED:
            error = supervised.error
            admission = supervised.admission
            reason_code = supervised.reason_code or "attempt_admission_rejected"
            details = {
                "attempt": attempt,
                "max_attempts": max_attempts,
                "started": False,
                "reason_code": reason_code,
                "admission": (
                    dict(admission.details) if admission is not None else {}
                ),
                "budget_exceeded": reason_code
                in {
                    "attempt_local_retry_exhausted",
                    "attempt_global_retry_exhausted",
                },
            }
            return StepOutcome(
                status=StepStatus.BLOCKED,
                error_type=(
                    type(error).__name__
                    if error is not None
                    else "AttemptAdmissionRejected"
                ),
                error_message=(
                    str(error) if error is not None else "attempt admission rejected"
                ),
                error_details=details,
            )
        if supervised.context is None:
            raise RuntimeError("started attempt outcome is missing context")

        if "value" not in attempt_buffer_holder:
            error = supervised.error
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=(
                    type(error).__name__
                    if error is not None
                    else "StepAttemptPreparationError"
                ),
                error_message=(
                    str(error)
                    if error is not None
                    else "step attempt preparation failed"
                ),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "attempt_id": supervised.context.attempt_id,
                    "idempotency_key": supervised.context.idempotency_key,
                    "operation_id": supervised.context.operation_id,
                    "local_attempt_no": supervised.context.local_attempt_no,
                    "retry_credit_id": supervised.context.retry_credit_id,
                    "termination_confirmed": supervised.termination_confirmed,
                    "indeterminate": supervised.indeterminate,
                },
            )

        deadline_details = dict(supervised.context.admission_details)
        effective_timeout = _effective_timeout_seconds(deadline_details)
        cancellation_source = _cancellation_source(deadline_details)
        if supervised.state is AttemptState.INDETERMINATE:
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=WORKFLOW_STEP_INDETERMINATE_ERROR,
                error_message=(
                    f"step {step.step_id} has an indeterminate descendant effect"
                ),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "attempt_id": supervised.context.attempt_id,
                    "idempotency_key": supervised.context.idempotency_key,
                    "operation_id": supervised.context.operation_id,
                    "local_attempt_no": supervised.context.local_attempt_no,
                    "retry_credit_id": supervised.context.retry_credit_id,
                    "termination_confirmed": supervised.termination_confirmed,
                    "indeterminate": True,
                },
            )
        if supervised.state is AttemptState.TIMED_OUT:
            indeterminate = (
                supervised.indeterminate
                or not _retry_is_safe(
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
                    "operation_id": supervised.context.operation_id,
                    "local_attempt_no": supervised.context.local_attempt_no,
                    "retry_credit_id": supervised.context.retry_credit_id,
                    "termination_confirmed": supervised.termination_confirmed,
                    "indeterminate": indeterminate,
                },
            )
        if supervised.state is AttemptState.FAILED:
            if isinstance(supervised.value, StepOutcome):
                return _with_attempt_context(
                    supervised.value,
                    supervised.context,
                )
            error = supervised.error
            indeterminate = (
                not _retry_is_safe(step, self._step_runner_registry)
                and not _step_failure_is_known_to_have_no_effect(step, error)
            )
            if indeterminate and parent_context is not None:
                parent_context.mark_descendant_indeterminate()
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=(
                    WORKFLOW_STEP_INDETERMINATE_ERROR
                    if indeterminate
                    else (
                        type(error).__name__
                        if error is not None
                        else "StepExecutionError"
                    )
                ),
                error_message=(str(error) if error is not None else "step attempt failed"),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "attempt_id": supervised.context.attempt_id,
                    "idempotency_key": supervised.context.idempotency_key,
                    "operation_id": supervised.context.operation_id,
                    "local_attempt_no": supervised.context.local_attempt_no,
                    "retry_credit_id": supervised.context.retry_credit_id,
                    "termination_confirmed": True,
                    "indeterminate": indeterminate,
                },
            )

        outcome = supervised.value
        if not isinstance(outcome, StepOutcome):
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type="StepExecutionError",
                error_message="step attempt returned an invalid outcome",
            )
        return _with_attempt_context(outcome, supervised.context)

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
                context.raise_if_indeterminate()
            runner = self._step_runner_registry.resolve(step)
            if runner is None:
                raise StepRunnerResolutionError(
                    "step runner cannot resolve step: "
                    f"{step.step_id} ({step.step_type.value}:{step.implementation})"
                )
            outcome = runner.run(step, scoped_buffer)
            if context is not None:
                context.raise_if_cancelled()
                context.raise_if_indeterminate()
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
    if _is_capacity_exhausted_outcome(outcome):
        return False
    if outcome.status == StepStatus.FAILED:
        if outcome.error_details.get("indeterminate") is True:
            return False
        return registry is None or _retry_is_safe(step, registry)
    if outcome.status == StepStatus.TIMEOUT:
        if step.timeout_policy.on_timeout != "retry":
            return False
        if outcome.error_details.get("termination_confirmed") is False:
            return False
        if outcome.error_details.get("indeterminate") is True:
            return False
        return registry is None or _retry_is_safe(step, registry)
    return False


def _effective_timeout_seconds(details: dict[str, object]) -> float | None:
    started = details.get("now_monotonic")
    completion = details.get("completion_until")
    if not isinstance(started, (int, float)) or not isinstance(
        completion, (int, float)
    ):
        return None
    return max(0.0, float(completion) - float(started))


def _cancellation_source(details: dict[str, object]) -> str:
    completion = details.get("completion_until")
    if not isinstance(completion, (int, float)):
        return "unbounded"
    candidates = (
        ("parent_attempt", details.get("parent_available_until")),
        ("root_hard_deadline", details.get("root_available_until")),
        ("step_deadline", details.get("requested_until")),
    )
    for source, value in candidates:
        if isinstance(value, (int, float)) and float(value) == float(completion):
            return source
    return "step_deadline"


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


def _retry_is_safe(
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


def _step_failure_is_known_to_have_no_effect(
    step: StepSpec,
    error: BaseException | None,
) -> bool:
    if error is None:
        return False
    if isinstance(error, StaleWorkflowAttemptError):
        # The attempt overlay validates ownership and restores the buffer
        # atomically before surfacing this error.
        return True
    configured = (step.metadata or {}).get("no_effect_error_types") or []
    if not isinstance(configured, list):
        return False
    error_types = {base.__name__ for base in type(error).__mro__}
    return bool(error_types.intersection(str(value) for value in configured))


def _step_outcome_failure_is_known_to_have_no_effect(
    step: StepSpec,
    outcome: StepOutcome,
) -> bool:
    configured = (step.metadata or {}).get("no_effect_error_types") or []
    if not isinstance(configured, list) or not outcome.error_type:
        return False
    return str(outcome.error_type) in {str(value) for value in configured}


def _step_outcome_has_confirmed_determinate_effect(outcome: StepOutcome) -> bool:
    return outcome.error_details.get("effect_determinacy_confirmed") is True


def _is_capacity_exhausted_outcome(outcome: StepOutcome) -> bool:
    error_type = str(outcome.error_type or "").casefold()
    return "attemptcapacityexhausted" in error_type or (
        "attempt" in error_type and "capacity" in error_type
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
        "operation_id": context.operation_id,
        "operation_kind": context.operation_kind,
        "local_attempt_no": context.local_attempt_no,
        "idempotency_key": context.idempotency_key,
        "retry_credit_id": context.retry_credit_id,
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


def _attempt_error_code(error: BaseException | None) -> str | None:
    if error is None:
        return None
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(error).__name__


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
