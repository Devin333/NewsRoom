from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ExecutionEnvironmentError(RuntimeError):
    """Typed failure raised at the Harness-controlled execution boundary."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        normalized = str(reason_code).strip()
        if not normalized:
            raise ValueError("reason_code is required")
        self.reason_code = normalized
        self.details = dict(details or {})


class ExecutionEnvironmentUnavailableError(ExecutionEnvironmentError):
    """The requested physical isolation cannot be proven by this deployment."""

    def __init__(
        self,
        message: str = "execution environment is unavailable",
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            reason_code="execution_environment_unavailable",
            details=details,
        )


class ExecutionPolicyViolationError(ExecutionEnvironmentError):
    """A normalized execution request violates its admitted profile."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "execution_policy_violation",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code, details=details)


class ExecutionIdentityMismatchError(ExecutionEnvironmentError):
    """A provider receipt is not bound to the admitted physical activity."""

    def __init__(
        self,
        message: str = "execution receipt identity does not match the request",
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            reason_code="execution_identity_mismatch",
            details=details,
        )


__all__ = [
    "ExecutionEnvironmentError",
    "ExecutionEnvironmentUnavailableError",
    "ExecutionIdentityMismatchError",
    "ExecutionPolicyViolationError",
]
