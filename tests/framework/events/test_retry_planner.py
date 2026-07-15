from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from framework.events import (
    ConsumerFailure,
    ConsumerFailureKind,
    DeliveryLeaseToken,
    DeliveryState,
    RetryPlanner,
    RetryPolicy,
)


FAILED_AT = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


def _failure(
    kind: ConsumerFailureKind = ConsumerFailureKind.TRANSIENT,
) -> ConsumerFailure:
    return ConsumerFailure(
        kind=kind,
        reason_class="backend_unavailable",
        redacted_diagnostic="connection_timeout",
    )


def test_retry_plan_uses_bounded_exponential_schedule_and_exhausts_to_dlq() -> None:
    planner = RetryPlanner()
    policy = RetryPolicy(jitter_ratio=0)

    plans = [
        planner.plan(
            failure=_failure(),
            attempt_count=attempt,
            policy=policy,
            failed_at=FAILED_AT,
            jitter_key="delivery-1",
        )
        for attempt in range(1, 6)
    ]

    assert [plan.delay_seconds for plan in plans[:4]] == [1.0, 2.0, 4.0, 8.0]
    assert all(plan.target_state is DeliveryState.RETRY_WAIT for plan in plans[:4])
    assert plans[4].target_state is DeliveryState.DEAD_LETTER
    assert plans[4].retry_available_at is None


def test_jitter_is_deterministic_bounded_and_never_exceeds_cap() -> None:
    planner = RetryPlanner()
    policy = RetryPolicy(
        max_attempts=5,
        initial_delay_seconds=2,
        multiplier=2,
        max_delay_seconds=3,
        jitter_ratio=0.2,
    )

    first = planner.plan(
        failure=_failure(),
        attempt_count=1,
        policy=policy,
        failed_at=FAILED_AT,
        jitter_key="delivery-stable",
    )
    repeated = planner.plan(
        failure=_failure(),
        attempt_count=1,
        policy=policy,
        failed_at=FAILED_AT,
        jitter_key="delivery-stable",
    )
    capped = planner.plan(
        failure=_failure(),
        attempt_count=2,
        policy=policy,
        failed_at=FAILED_AT,
        jitter_key="delivery-stable",
    )

    assert first == repeated
    assert first.delay_seconds is not None
    assert 1.6 <= first.delay_seconds <= 2.4
    assert capped.delay_seconds is not None
    assert capped.delay_seconds <= 3


def test_permanent_failure_routes_directly_to_dlq_without_consuming_more_budget() -> None:
    plan = RetryPlanner().plan(
        failure=_failure(ConsumerFailureKind.PERMANENT),
        attempt_count=1,
        policy=RetryPolicy(),
        failed_at=FAILED_AT,
        jitter_key="delivery-permanent",
    )

    assert plan.target_state is DeliveryState.DEAD_LETTER
    assert plan.delay_seconds is None


def test_retry_plan_builds_fenced_settlement() -> None:
    plan = RetryPlanner().plan(
        failure=_failure(),
        attempt_count=1,
        policy=RetryPolicy(jitter_ratio=0),
        failed_at=FAILED_AT,
        jitter_key="delivery-1",
    )
    lease = DeliveryLeaseToken(
        delivery_id="delivery-1",
        delivery_generation=1,
        lease_owner="worker-1",
        lease_generation=1,
        lease_expires_at=FAILED_AT + timedelta(seconds=30),
    )

    settlement = plan.settlement(lease)

    assert settlement.target_state is DeliveryState.RETRY_WAIT
    assert settlement.retry_available_at == FAILED_AT + timedelta(seconds=1)
    assert settlement.reason_class == "backend_unavailable"


def test_retry_planner_rejects_naive_time_and_invalid_attempt() -> None:
    planner = RetryPlanner()

    with pytest.raises(ValueError, match="timezone-aware"):
        planner.plan(
            failure=_failure(),
            attempt_count=1,
            policy=RetryPolicy(),
            failed_at=datetime(2026, 7, 15, 10, 0),
            jitter_key="delivery-1",
        )
    with pytest.raises(ValueError, match="positive integer"):
        planner.plan(
            failure=_failure(),
            attempt_count=0,
            policy=RetryPolicy(),
            failed_at=FAILED_AT,
            jitter_key="delivery-1",
        )

