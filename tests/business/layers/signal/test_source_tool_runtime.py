from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from business.foundation.models.source import SourceDefinition, SourceFetchPolicy, SourceType
from business.layers.signal.source_processing.error_metadata import SOURCE_ERROR_RUNTIME_METADATA_KEY
from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY
from business.layers.signal import source_tool_runtime
from business.layers.signal.source_tool_runtime import (
    SourceRateLimitDecision,
    SourceRateLimiter,
    source_fetch_policy_without_rate_limit,
    source_rate_limited_error,
)


def test_source_rate_limited_error_writes_formal_runtime_and_policy_metadata() -> None:
    error = source_rate_limited_error(
        SourceDefinition(
            source_id="feed",
            name="Feed",
            source_type=SourceType.RSS,
            url="https://example.com/feed.xml",
        ),
        SourceRateLimitDecision(
            allowed=False,
            domain="example.com",
            limit_per_minute=2,
            retry_after_seconds=30,
        ),
        url="https://example.com/feed.xml",
    )

    assert error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "fetch",
        "retryable": True,
        "source_health_affecting": False,
    }
    assert error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": False,
        "workflow_blocking": False,
        "operator_action_required": False,
    }
    assert error.metadata["phase"] == "fetch"
    assert error.metadata["source_health_affecting"] is False
    assert error.metadata["domain"] == "example.com"
    assert error.metadata["limit_per_minute"] == 2
    assert error.metadata["retry_after_seconds"] == 30


def test_source_rate_limiter_is_a_port_with_an_immutable_decision() -> None:
    class FakeRateLimiter:
        def reserve(self, url: str, *, limit_per_minute: int | None) -> SourceRateLimitDecision:
            return SourceRateLimitDecision(
                allowed=True,
                domain="example.com",
                limit_per_minute=limit_per_minute,
            )

    limiter: SourceRateLimiter = FakeRateLimiter()
    decision = limiter.reserve("https://example.com/feed.xml", limit_per_minute=2)

    assert decision == SourceRateLimitDecision(
        allowed=True,
        domain="example.com",
        limit_per_minute=2,
    )
    with pytest.raises(FrozenInstanceError):
        decision.allowed = False  # type: ignore[misc]


def test_business_source_runtime_exports_no_limiter_or_retry_algorithm() -> None:
    assert not hasattr(source_tool_runtime, "SourceDomainRateLimiter")
    assert not hasattr(source_tool_runtime, "run_fetch_with_retries")
    assert not hasattr(source_tool_runtime, "_is_retryable_fetch_exception")


def test_source_fetch_policy_without_rate_limit_preserves_retry_contract() -> None:
    policy = SourceFetchPolicy(
        rate_limit_per_domain_per_minute=2,
        retry_times=4,
        retry_on_status_codes=(404, 503),
        allowed_domains=("example.com",),
    )

    result = source_fetch_policy_without_rate_limit(policy)

    assert result.rate_limit_per_domain_per_minute is None
    assert result.retry_times == 4
    assert result.retry_on_status_codes == (404, 503)
    assert result.allowed_domains == ("example.com",)
