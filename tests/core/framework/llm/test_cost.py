import pytest

from core.framework.llm import (
    CostEstimator,
    GlobalBudgetExceededError,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMBudgetExceededError,
    LLMBudgetGuard,
    LLMBudgetPolicy,
    ModelPricing,
    TokenUsage,
)


def test_cost_estimator_sums_input_and_output_cost() -> None:
    usage = TokenUsage(input_tokens=1_000, output_tokens=500)
    pricing = ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0)

    cost = CostEstimator().estimate(usage, pricing)

    assert cost == 0.007


def test_cost_estimator_treats_missing_pricing_as_zero() -> None:
    usage = TokenUsage(input_tokens=1_000, output_tokens=500)
    pricing = ModelPricing(input_usd_per_1m_tokens=2.0)

    cost = CostEstimator().estimate(usage, pricing)

    assert cost == 0.002
    assert CostEstimator().estimate(usage, None) == 0.0


def test_budget_guard_returns_within_budget_check() -> None:
    guard = LLMBudgetGuard(
        LLMBudgetPolicy(max_tokens_per_call=20, max_cost_per_call_usd=0.01)
    )

    check = guard.check_call(
        TokenUsage(input_tokens=5, output_tokens=5),
        ModelPricing(input_usd_per_1m_tokens=1.0, output_usd_per_1m_tokens=1.0),
    )

    assert check.within_budget is True
    assert check.violations == ()
    assert check.to_dict()["usage"]["total_tokens"] == 10


def test_budget_guard_raises_for_token_violation_in_fail_mode() -> None:
    guard = LLMBudgetGuard(LLMBudgetPolicy(max_tokens_per_call=9))

    with pytest.raises(LLMBudgetExceededError) as exc_info:
        guard.check_call(TokenUsage(input_tokens=5, output_tokens=5))

    assert exc_info.value.check.violations == ("max_tokens_per_call",)
    assert exc_info.value.to_dict()["error_type"] == "llm_budget_exceeded"


def test_budget_guard_raises_for_cost_violation_in_fail_mode() -> None:
    guard = LLMBudgetGuard(LLMBudgetPolicy(max_cost_per_call_usd=0.001))

    with pytest.raises(LLMBudgetExceededError) as exc_info:
        guard.check_call(
            TokenUsage(input_tokens=1_000, output_tokens=500),
            ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0),
        )

    assert exc_info.value.check.estimated_cost_usd == 0.007
    assert exc_info.value.check.violations == ("max_cost_per_call_usd",)


def test_budget_guard_non_fail_mode_returns_failed_check() -> None:
    guard = LLMBudgetGuard(
        LLMBudgetPolicy(max_cost_per_call_usd=0.001, on_budget_exceeded="ask_approval")
    )

    check = guard.check_call(
        TokenUsage(input_tokens=1_000, output_tokens=500),
        ModelPricing(input_usd_per_1m_tokens=2.0, output_usd_per_1m_tokens=10.0),
    )

    assert check.within_budget is False
    assert check.violations == ("max_cost_per_call_usd",)


def test_global_budget_tracker_accumulates_llm_usage_and_cost() -> None:
    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=2, max_total_tokens=40, max_total_cost_usd=0.01)
    )

    first = tracker.record_llm_call(
        TokenUsage(input_tokens=10, output_tokens=5),
        ModelPricing(input_usd_per_1m_tokens=100.0, output_usd_per_1m_tokens=100.0),
    )
    second = tracker.record_llm_call(
        TokenUsage(input_tokens=8, output_tokens=7),
        estimated_cost_usd=0.0015,
    )

    assert first.within_budget is True
    assert second.within_budget is True
    assert second.usage.llm_calls == 2
    assert second.usage.token_usage.total_tokens == 30
    assert second.usage.estimated_cost_usd == 0.003
    assert tracker.snapshot()["llm_calls"] == 2


def test_global_budget_tracker_blocks_preflight_when_call_limit_would_be_exceeded() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=1))
    tracker.record_llm_call(TokenUsage(input_tokens=1, output_tokens=1))

    with pytest.raises(GlobalBudgetExceededError) as exc_info:
        tracker.check_before_llm_call()

    assert exc_info.value.check.violations == ("max_llm_calls",)
    assert exc_info.value.check.usage.llm_calls == 2


def test_global_budget_tracker_reserves_prompt_tokens_then_replaces_with_actual_usage() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=1, max_total_tokens=20))

    preflight = tracker.reserve_llm_call(estimated_prompt_tokens=9)
    actual = tracker.record_llm_call(
        TokenUsage(input_tokens=4, output_tokens=3),
        replace_reserved_prompt_tokens=9,
        count_request=False,
    )

    assert preflight.usage.llm_calls == 1
    assert preflight.usage.token_usage.input_tokens == 9
    assert actual.usage.llm_calls == 1
    assert actual.usage.token_usage.total_tokens == 7


def test_global_budget_tracker_cache_hit_counts_request_without_cost() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=2, max_total_cost_usd=0.0))

    check = tracker.record_llm_call(
        TokenUsage(input_tokens=10, output_tokens=0, estimated_cost_usd=0.0)
    )

    assert check.usage.llm_calls == 1
    assert check.usage.estimated_cost_usd == 0.0


def test_global_budget_tracker_raises_after_total_token_violation() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_total_tokens=3))

    with pytest.raises(GlobalBudgetExceededError) as exc_info:
        tracker.record_llm_call(TokenUsage(input_tokens=2, output_tokens=2))

    assert exc_info.value.check.violations == ("max_total_tokens",)
    assert tracker.usage.token_usage.total_tokens == 4
