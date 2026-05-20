from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.errors import ValidationError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float | None = None
    retryable_errors: tuple[str, ...] = field(default_factory=tuple)
    non_retryable_errors: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValidationError("max_attempts must be at least 1", code="invalid_retry_policy")
        if self.base_delay_seconds < 0:
            raise ValidationError("base_delay_seconds must be non-negative", code="invalid_retry_policy")
        if self.backoff_multiplier < 0:
            raise ValidationError("backoff_multiplier must be non-negative", code="invalid_retry_policy")
        if self.max_delay_seconds is not None and self.max_delay_seconds < 0:
            raise ValidationError("max_delay_seconds must be non-negative", code="invalid_retry_policy")

    def should_retry(self, attempt: int, error: Any) -> bool:
        if attempt >= self.max_attempts:
            return False
        error_name = _error_name(error)
        if error_name in self.non_retryable_errors:
            return False
        if not self.retryable_errors:
            return True
        return error_name in self.retryable_errors

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise ValidationError("attempt must be at least 1", code="invalid_retry_attempt")
        delay = self.base_delay_seconds * (self.backoff_multiplier ** (attempt - 1))
        if self.max_delay_seconds is not None:
            return min(delay, self.max_delay_seconds)
        return delay


def _error_name(error: Any) -> str:
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        value = error.get("error_type") or error.get("type") or error.get("code")
        if value:
            return str(value)
    value = getattr(error, "error_type", None) or getattr(error, "code", None)
    if value:
        return str(value)
    return error.__class__.__name__
