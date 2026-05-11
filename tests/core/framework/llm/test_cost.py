import pytest

from core.framework.llm import (
    CostEstimator,
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
