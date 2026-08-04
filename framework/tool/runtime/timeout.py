from __future__ import annotations

from typing import Any

from framework.shared.attempts import (
    AttemptState,
    AttemptSupervisor,
    DeadlineAdmissionPolicy,
    ExecutionLimits,
    LocalRetryBudget,
    RetryCreditLedger,
    current_attempt_context,
)
from framework.tool.runtime.errors import ToolRuntimeError, ToolTimeoutError


class ToolTimeoutRunner:
    def __init__(
        self,
        *,
        cancellation_grace_seconds: float = 0.1,
        min_start_window_seconds: float = 0.0,
        completion_reserve_seconds: float = 0.0,
    ) -> None:
        self._cancellation_grace_seconds = cancellation_grace_seconds
        self._min_start_window_seconds = min_start_window_seconds
        self._completion_reserve_seconds = completion_reserve_seconds

    def run(self, fn: Any, timeout_seconds: float | None, *, operation: str = "tool") -> Any:
        return run_with_timeout(
            fn,
            timeout_seconds,
            operation=operation,
            cancellation_grace_seconds=self._cancellation_grace_seconds,
            min_start_window_seconds=self._min_start_window_seconds,
            completion_reserve_seconds=self._completion_reserve_seconds,
        )


def run_with_timeout(
    fn: Any,
    timeout_seconds: float | None,
    *,
    operation: str = "tool",
    cancellation_grace_seconds: float = 0.1,
    min_start_window_seconds: float = 0.0,
    completion_reserve_seconds: float = 0.0,
    idempotency_key: str | None = None,
) -> Any:
    parent_context = current_attempt_context()
    logical_key = idempotency_key or f"tool-operation:{operation}"
    execution_limits = (
        parent_context.execution_limits
        if parent_context is not None
        and parent_context.execution_limits is not None
        else ExecutionLimits(
            execution_id=f"standalone:{logical_key}",
            retry_credits=RetryCreditLedger(max_total_retries=0),
        )
    )
    outcome = AttemptSupervisor(
        cancellation_grace_seconds=cancellation_grace_seconds
    ).run(
        fn,
        timeout_seconds=timeout_seconds,
        idempotency_key=logical_key,
        operation_id=logical_key,
        operation_kind="tool_operation",
        local_budget=LocalRetryBudget(max_attempts=1),
        admission_policy=DeadlineAdmissionPolicy(
            timeout_seconds=timeout_seconds,
            min_start_window_seconds=min_start_window_seconds,
            cancellation_grace_seconds=cancellation_grace_seconds,
            completion_reserve_seconds=completion_reserve_seconds,
            admission_details={"operation": operation},
        ),
        execution_limits=execution_limits,
        parent_context=parent_context,
    )
    if outcome.state is AttemptState.REJECTED:
        if outcome.error is None:
            raise ToolRuntimeError(
                "tool operation admission was rejected without an error"
            )
        raise outcome.error
    if outcome.state is AttemptState.SUCCEEDED:
        return outcome.value
    if outcome.state is AttemptState.FAILED:
        if outcome.error is None:
            raise ToolRuntimeError("tool operation failed without an error")
        raise outcome.error
    if outcome.state is AttemptState.INDETERMINATE:
        if outcome.error is not None:
            raise outcome.error
        raise ToolRuntimeError("tool operation has an indeterminate outcome")
    timeout_text = (
        f"{float(timeout_seconds):g} seconds"
        if timeout_seconds is not None
        else "its deadline"
    )
    raise ToolTimeoutError(
        f"{operation} exceeded timeout of {timeout_text}",
        attempt_id=outcome.context.attempt_id,
        idempotency_key=outcome.context.idempotency_key,
        operation_id=outcome.context.operation_id,
        operation_kind=outcome.context.operation_kind,
        local_attempt_no=outcome.context.local_attempt_no,
        retry_credit_id=outcome.context.retry_credit_id,
        termination_confirmed=outcome.termination_confirmed,
        indeterminate=outcome.indeterminate,
    )
