from __future__ import annotations

from typing import Any

from framework.shared.attempts import (
    AttemptState,
    AttemptSupervisor,
    current_attempt_context,
)
from framework.tool.runtime.errors import ToolRuntimeError, ToolTimeoutError


class ToolTimeoutRunner:
    def __init__(self, *, cancellation_grace_seconds: float = 0.1) -> None:
        self._cancellation_grace_seconds = cancellation_grace_seconds

    def run(self, fn: Any, timeout_seconds: float | None, *, operation: str = "tool") -> Any:
        return run_with_timeout(
            fn,
            timeout_seconds,
            operation=operation,
            cancellation_grace_seconds=self._cancellation_grace_seconds,
        )


def run_with_timeout(
    fn: Any,
    timeout_seconds: float | None,
    *,
    operation: str = "tool",
    cancellation_grace_seconds: float = 0.1,
    idempotency_key: str | None = None,
) -> Any:
    parent_context = current_attempt_context()
    outcome = AttemptSupervisor(
        cancellation_grace_seconds=cancellation_grace_seconds
    ).run(
        fn,
        timeout_seconds=timeout_seconds,
        idempotency_key=idempotency_key or f"tool-operation:{operation}",
        parent_context=parent_context,
    )
    if outcome.state is AttemptState.SUCCEEDED:
        return outcome.value
    if outcome.state is AttemptState.FAILED:
        if outcome.error is None:
            raise ToolRuntimeError("tool operation failed without an error")
        raise outcome.error
    timeout_text = (
        f"{float(timeout_seconds):g} seconds"
        if timeout_seconds is not None
        else "its deadline"
    )
    raise ToolTimeoutError(
        f"{operation} exceeded timeout of {timeout_text}",
        attempt_id=outcome.context.attempt_id,
        idempotency_key=outcome.context.idempotency_key,
        fencing_token=outcome.context.fencing_token,
        termination_confirmed=outcome.termination_confirmed,
        indeterminate=outcome.indeterminate,
    )
