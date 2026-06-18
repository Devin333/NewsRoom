from __future__ import annotations

from framework.llm.budget.pricing import ModelPricing


class CostEstimator:
    def estimate(
        self,
        request_or_usage,
        response=None,
        pricing: ModelPricing | None = None,
    ) -> float:
        usage = request_or_usage
        if response is not None and hasattr(response, "usage"):
            usage = response.usage
        elif response is not None and pricing is None:
            pricing = response
        if usage.estimated_cost_usd is not None:
            return round(float(usage.estimated_cost_usd), 12)
        if pricing is None:
            return 0.0
        billed_input_tokens = max(usage.input_tokens - usage.cached_input_tokens, 0)
        input_cost = _component_cost(billed_input_tokens, pricing.input_usd_per_1m_tokens)
        output_cost = _component_cost(usage.output_tokens, pricing.output_usd_per_1m_tokens)
        return round(input_cost + output_cost, 12)


def _component_cost(tokens: int, usd_per_1m_tokens: float | None) -> float:
    if usd_per_1m_tokens is None:
        return 0.0
    return tokens * usd_per_1m_tokens / 1_000_000

