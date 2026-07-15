from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from framework.events.runtime.models import (
    DeliveryLeaseToken,
    DeliverySettlement,
    DeliveryState,
    RetryPolicy,
)
from framework.events.subscriber import ConsumerFailure, ConsumerFailureKind


@dataclass(frozen=True, slots=True)
class RetryPlan:
    target_state: DeliveryState
    attempt_count: int
    failed_at: datetime
    reason_class: str
    redacted_diagnostic: str | None
    delay_seconds: float | None = None
    retry_available_at: datetime | None = None

    def __post_init__(self) -> None:
        state = DeliveryState(self.target_state)
        if state not in {DeliveryState.RETRY_WAIT, DeliveryState.DEAD_LETTER}:
            raise ValueError("retry plan target must be RETRY_WAIT or DEAD_LETTER")
        if isinstance(self.attempt_count, bool) or not isinstance(self.attempt_count, int):
            raise ValueError("attempt_count must be a positive integer")
        if self.attempt_count < 1:
            raise ValueError("attempt_count must be a positive integer")
        failed_at = _utc(self.failed_at)
        if not self.reason_class.strip():
            raise ValueError("reason_class is required")
        if state is DeliveryState.RETRY_WAIT:
            if self.delay_seconds is None or self.delay_seconds <= 0:
                raise ValueError("RETRY_WAIT plan requires a positive delay")
            retry_at = _utc(self.retry_available_at)
            if retry_at <= failed_at:
                raise ValueError("retry_available_at must be after failed_at")
        elif self.delay_seconds is not None or self.retry_available_at is not None:
            raise ValueError("DEAD_LETTER plan cannot schedule another retry")
        object.__setattr__(self, "target_state", state)
        object.__setattr__(self, "failed_at", failed_at)

    def settlement(self, lease: DeliveryLeaseToken) -> DeliverySettlement:
        return DeliverySettlement(
            lease=lease,
            target_state=self.target_state,
            settled_at=self.failed_at,
            reason_class=self.reason_class,
            redacted_diagnostic=self.redacted_diagnostic,
            retry_available_at=self.retry_available_at,
        )


class RetryPlanner:
    """Bounded exponential retry with deterministic, replayable jitter."""

    def plan(
        self,
        *,
        failure: ConsumerFailure,
        attempt_count: int,
        policy: RetryPolicy,
        failed_at: datetime,
        jitter_key: str,
    ) -> RetryPlan:
        if not isinstance(failure, ConsumerFailure):
            raise TypeError("failure must be ConsumerFailure")
        if not isinstance(policy, RetryPolicy):
            raise TypeError("policy must be RetryPolicy")
        if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
            raise ValueError("attempt_count must be a positive integer")
        if attempt_count < 1:
            raise ValueError("attempt_count must be a positive integer")
        failed_at = _utc(failed_at)
        if not isinstance(jitter_key, str) or not jitter_key.strip():
            raise ValueError("jitter_key is required")

        if (
            failure.kind is ConsumerFailureKind.PERMANENT
            or not policy.can_retry(attempt_count)
        ):
            return RetryPlan(
                target_state=DeliveryState.DEAD_LETTER,
                attempt_count=attempt_count,
                failed_at=failed_at,
                reason_class=failure.reason_class,
                redacted_diagnostic=failure.redacted_diagnostic,
            )

        base = policy.base_delay_seconds(attempt_count)
        fraction = _deterministic_fraction(jitter_key.strip(), attempt_count)
        multiplier = 1.0 + policy.jitter_ratio * ((fraction * 2.0) - 1.0)
        delay = min(policy.max_delay_seconds, base * multiplier)
        retry_at = failed_at + timedelta(seconds=delay)
        return RetryPlan(
            target_state=DeliveryState.RETRY_WAIT,
            attempt_count=attempt_count,
            failed_at=failed_at,
            reason_class=failure.reason_class,
            redacted_diagnostic=failure.redacted_diagnostic,
            delay_seconds=delay,
            retry_available_at=retry_at,
        )


def _deterministic_fraction(jitter_key: str, attempt_count: int) -> float:
    digest = sha256(f"{jitter_key}:{attempt_count}".encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], "big")
    return integer / ((1 << 64) - 1)


def _utc(value: datetime | None) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("failed_at and retry_available_at must be datetimes")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("failed_at and retry_available_at must be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["RetryPlan", "RetryPlanner"]
