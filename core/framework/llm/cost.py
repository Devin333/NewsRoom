from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.framework.llm.models import TokenUsage


BudgetMode = Literal["fail", "fallback", "ask_approval", "warn"]


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_1m_tokens: float | None = None
    output_usd_per_1m_tokens: float | None = None


class CostEstimator:
    def estimate(self, usage: TokenUsage, pricing: ModelPricing | None) -> float:
        if pricing is None:
            return 0.0
        input_cost = _component_cost(usage.input_tokens, pricing.input_usd_per_1m_tokens)
        output_cost = _component_cost(usage.output_tokens, pricing.output_usd_per_1m_tokens)
        return round(input_cost + output_cost, 12)


@dataclass(frozen=True)
class LLMBudgetPolicy:
    max_cost_per_call_usd: float | None = None
    max_tokens_per_call: int | None = None
    on_budget_exceeded: BudgetMode = "fail"


@dataclass(frozen=True)
class LLMBudgetCheck:
    usage: TokenUsage
    estimated_cost_usd: float
    within_budget: bool
    violations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "usage": self.usage.to_dict(),
            "estimated_cost_usd": self.estimated_cost_usd,
            "within_budget": self.within_budget,
            "violations": list(self.violations),
        }


class LLMBudgetExceededError(RuntimeError):
    def __init__(self, check: LLMBudgetCheck) -> None:
        super().__init__("LLM budget exceeded: " + ", ".join(check.violations))
        self.check = check

    def to_dict(self) -> dict[str, object]:
        return {
            "message": str(self),
            "error_type": "llm_budget_exceeded",
            "budget_check": self.check.to_dict(),
        }


class LLMBudgetGuard:
    def __init__(
        self,
        policy: LLMBudgetPolicy,
        *,
        estimator: CostEstimator | None = None,
    ) -> None:
        self.policy = policy
        self.estimator = estimator or CostEstimator()

    def check_call(self, usage: TokenUsage, pricing: ModelPricing | None = None) -> LLMBudgetCheck:
        estimated_cost_usd = self.estimator.estimate(usage, pricing)
        violations = self._violations(usage, estimated_cost_usd)
        check = LLMBudgetCheck(
            usage=usage,
            estimated_cost_usd=estimated_cost_usd,
            within_budget=not violations,
            violations=tuple(violations),
        )
        if violations and self.policy.on_budget_exceeded == "fail":
            raise LLMBudgetExceededError(check)
        return check

    def _violations(self, usage: TokenUsage, estimated_cost_usd: float) -> list[str]:
        violations: list[str] = []
        if (
            self.policy.max_tokens_per_call is not None
            and usage.total_tokens > self.policy.max_tokens_per_call
        ):
            violations.append("max_tokens_per_call")
        if (
            self.policy.max_cost_per_call_usd is not None
            and estimated_cost_usd > self.policy.max_cost_per_call_usd
        ):
            violations.append("max_cost_per_call_usd")
        return violations


def _component_cost(tokens: int, usd_per_1m_tokens: float | None) -> float:
    if usd_per_1m_tokens is None:
        return 0.0
    return tokens * usd_per_1m_tokens / 1_000_000
