from __future__ import annotations


class ToolRuntimeError(RuntimeError):
    """Base exception for ToolRuntime failures."""


class ToolDefinitionError(ToolRuntimeError):
    """Raised when a tool definition is invalid."""


class ToolPermissionError(ToolRuntimeError):
    """Raised when an agent is not allowed to call a tool."""


class ToolTimeoutError(ToolRuntimeError):
    """Raised when a tool exceeds its execution timeout."""

    def __init__(
        self,
        message: str,
        *,
        attempt_id: str | None = None,
        idempotency_key: str | None = None,
        fencing_token: int | None = None,
        termination_confirmed: bool = False,
        indeterminate: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.attempt_id = attempt_id
        self.idempotency_key = idempotency_key
        self.fencing_token = fencing_token
        self.termination_confirmed = bool(termination_confirmed)
        self.indeterminate = (
            not self.termination_confirmed
            if indeterminate is None
            else bool(indeterminate)
        )


class ToolSecretError(ToolRuntimeError):
    """Raised when a tool secret cannot be safely resolved."""
