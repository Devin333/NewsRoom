from __future__ import annotations

from dataclasses import dataclass, field

from framework.llm.budget.estimator import CostEstimator
from framework.llm.budget.policy import LLMBudgetPolicy
from framework.llm.budget.pricing import ModelPricing
from framework.llm.models.usage import TokenUsage


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

    def check(self, usage: TokenUsage, pricing: ModelPricing | None = None) -> LLMBudgetCheck:
        return self.check_call(usage, pricing)

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

