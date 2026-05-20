from __future__ import annotations

from datetime import timedelta

import pytest

from framework.governance.policy import (
    CostPolicy,
    ExecutionPolicy,
    ResourcePolicy,
    RetryPolicy,
    SafetyPolicy,
    TimeoutPolicy,
)
from framework.shared.errors import ValidationError
from framework.shared.time import utc_now


def test_execution_policy_can_block_execution() -> None:
    assert ExecutionPolicy().can_execute({"step": "x"}) == (True, None)
    assert ExecutionPolicy(enabled=False, disabled_reason="paused").can_execute({}) == (False, "paused")


def test_safety_policy_checks_payload_and_tool_call() -> None:
    policy = SafetyPolicy(
        blocked_tool_names=("danger.delete",),
        blocked_tool_namespaces=("admin",),
        max_payload_bytes=8,
    )

    violations = policy.check_payload({"nested": {"api_key": "secret"}, "body": "too long"})
    assert any("nested.api_key" in violation for violation in violations)
    assert any("payload size" in violation for violation in violations)
    assert policy.check_tool_call({"name": "danger.delete"}) == ["tool danger.delete is blocked"]
    assert policy.check_tool_call({"name": "admin.reset"}) == ["tool namespace admin is blocked"]


def test_cost_policy_tracks_spend_and_rejects_negative_amounts() -> None:
    policy = CostPolicy(limit=10, spent=2)

    assert policy.can_spend(8)
    assert not policy.can_spend(9)
    policy.record(3)
    assert policy.remaining() == 5
    with pytest.raises(ValidationError):
        policy.record(-1)


def test_resource_policy_returns_violations() -> None:
    policy = ResourcePolicy(max_cpu_units=2, max_memory_mb=512, max_runtime_seconds=30)

    assert policy.check_cpu({"cpu_units": 3}) == ["cpu units estimate 3 exceeds limit 2"]
    assert policy.check_memory({"memory_mb": 256}) == []
    assert policy.check_runtime({"runtime_seconds": 45}) == ["runtime seconds estimate 45 exceeds limit 30"]


def test_retry_policy_supports_error_filters_and_backoff() -> None:
    policy = RetryPolicy(
        max_attempts=3,
        base_delay_seconds=2,
        backoff_multiplier=3,
        max_delay_seconds=10,
        retryable_errors=("TimeoutError",),
        non_retryable_errors=("ValidationError",),
    )

    assert policy.should_retry(1, "TimeoutError")
    assert not policy.should_retry(1, "ValidationError")
    assert not policy.should_retry(3, "TimeoutError")
    assert policy.delay_for_attempt(1) == 2
    assert policy.delay_for_attempt(3) == 10


def test_timeout_policy_uses_utc_deadlines() -> None:
    start = utc_now()
    policy = TimeoutPolicy(timeout_seconds=5)

    assert policy.deadline_from(start) == start + timedelta(seconds=5)
    assert not policy.is_expired(start, now=start + timedelta(seconds=4))
    assert policy.is_expired(start, now=start + timedelta(seconds=5))
    assert TimeoutPolicy().deadline_from(start) is None
