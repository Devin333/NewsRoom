import pytest

from core.framework.llm import (
    ContextPolicy,
    LLMContextGuard,
    LLMContextWindowExceededError,
    LLMRequest,
    estimate_request_tokens,
)


def test_estimate_request_tokens_is_deterministic() -> None:
    request = LLMRequest(messages=[{"role": "user", "content": "hello world"}])

    first = estimate_request_tokens(request)
    second = estimate_request_tokens(request)

    assert first > 0
    assert first == second


def test_context_guard_returns_check_when_request_fits() -> None:
    request = LLMRequest(messages=[{"role": "user", "content": "hello"}])
    guard = LLMContextGuard(ContextPolicy(max_context_tokens=100, reserve_output_tokens=10))

    check = guard.check_request(request)

    assert check.within_context is True
    assert check.projected_total_tokens == check.estimated_input_tokens + 10
    assert check.to_dict()["truncate_strategy"] == "require_compaction"


def test_context_guard_allows_boundary_value() -> None:
    request = LLMRequest(messages=[{"role": "user", "content": "hello"}])
    estimated = estimate_request_tokens(request)
    guard = LLMContextGuard(
        ContextPolicy(max_context_tokens=estimated + 5, reserve_output_tokens=5)
    )

    check = guard.check_request(request)

    assert check.projected_total_tokens == check.max_context_tokens


def test_context_guard_raises_when_request_exceeds_window() -> None:
    request = LLMRequest(messages=[{"role": "user", "content": "x" * 200}])
    guard = LLMContextGuard(
        ContextPolicy(max_context_tokens=10, reserve_output_tokens=5, truncate_strategy="fail")
    )

    with pytest.raises(LLMContextWindowExceededError) as exc_info:
        guard.check_request(request)

    assert exc_info.value.check.within_context is False
    assert exc_info.value.check.truncate_strategy == "fail"
    assert exc_info.value.to_dict()["error_type"] == "context_length_exceeded"


def test_context_policy_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="max_context_tokens"):
        ContextPolicy(max_context_tokens=0)
    with pytest.raises(ValueError, match="reserve_output_tokens"):
        ContextPolicy(max_context_tokens=10, reserve_output_tokens=-1)
