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
        if usage.estimated_cost_usd is not None:
            return round(float(usage.estimated_cost_usd), 12)
        if pricing is None:
            return 0.0
        billed_input_tokens = max(usage.input_tokens - usage.cached_input_tokens, 0)
        input_cost = _component_cost(billed_input_tokens, pricing.input_usd_per_1m_tokens)
        output_cost = _component_cost(usage.output_tokens, pricing.output_usd_per_1m_tokens)
        return round(input_cost + output_cost, 12)


@dataclass(frozen=True)
class LLMBudgetPolicy:
    max_cost_per_call_usd: float | None = None
    max_tokens_per_call: int | None = None
    on_budget_exceeded: BudgetMode = "fail"


@dataclass(frozen=True)
class GlobalBudgetPolicy:
    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None
    max_llm_calls: int | None = None
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


@dataclass(frozen=True)
class GlobalBudgetUsage:
    llm_calls: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "llm_calls": self.llm_calls,
            "token_usage": self.token_usage.to_dict(),
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass(frozen=True)
class GlobalBudgetCheck:
    usage: GlobalBudgetUsage
    within_budget: bool
    violations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "usage": self.usage.to_dict(),
            "within_budget": self.within_budget,
            "violations": list(self.violations),
        }


class GlobalBudgetExceededError(RuntimeError):
    def __init__(self, check: GlobalBudgetCheck) -> None:
        super().__init__("global budget exceeded: " + ", ".join(check.violations))
        self.check = check

    def to_dict(self) -> dict[str, object]:
        return {
            "message": str(self),
            "error_type": "global_budget_exceeded",
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


class GlobalBudgetTracker:
    def __init__(
        self,
        policy: GlobalBudgetPolicy,
        *,
        estimator: CostEstimator | None = None,
    ) -> None:
        self.policy = policy
        self.estimator = estimator or CostEstimator()
        self._usage = GlobalBudgetUsage()

    @property
    def usage(self) -> GlobalBudgetUsage:
        return self._usage

    def snapshot(self) -> dict[str, object]:
        return self._usage.to_dict()

    def check_before_llm_call(
        self,
        estimated_prompt_tokens: int | None = None,
    ) -> GlobalBudgetCheck:
        next_usage = self._preflight_usage(estimated_prompt_tokens=estimated_prompt_tokens)
        return self._check(next_usage, preflight=True)

    def reserve_llm_call(
        self,
        estimated_prompt_tokens: int | None = None,
    ) -> GlobalBudgetCheck:
        next_usage = self._preflight_usage(estimated_prompt_tokens=estimated_prompt_tokens)
        check = self._check(next_usage, preflight=True)
        self._usage = next_usage
        return check

    def _preflight_usage(self, *, estimated_prompt_tokens: int | None) -> GlobalBudgetUsage:
        prompt_tokens = _non_negative_token_estimate(estimated_prompt_tokens)
        next_usage = GlobalBudgetUsage(
            llm_calls=self._usage.llm_calls + 1,
            token_usage=TokenUsage(
                input_tokens=self._usage.token_usage.input_tokens + prompt_tokens,
                output_tokens=self._usage.token_usage.output_tokens,
                reasoning_tokens=self._usage.token_usage.reasoning_tokens,
                cached_input_tokens=self._usage.token_usage.cached_input_tokens,
            ),
            estimated_cost_usd=self._usage.estimated_cost_usd,
        )
        return next_usage

    def record_llm_call(
        self,
        usage: TokenUsage,
        pricing: ModelPricing | None = None,
        *,
        estimated_cost_usd: float | None = None,
        replace_reserved_prompt_tokens: int | None = None,
        count_request: bool = True,
    ) -> GlobalBudgetCheck:
        call_cost = (
            round(float(estimated_cost_usd), 12)
            if estimated_cost_usd is not None
            else self.estimator.estimate(usage, pricing)
        )
        reserved_prompt_tokens = _non_negative_token_estimate(replace_reserved_prompt_tokens)
        next_usage = GlobalBudgetUsage(
            llm_calls=self._usage.llm_calls + (1 if count_request else 0),
            token_usage=TokenUsage(
                input_tokens=(
                    self._usage.token_usage.input_tokens
                    - reserved_prompt_tokens
                    + usage.input_tokens
                ),
                output_tokens=self._usage.token_usage.output_tokens + usage.output_tokens,
                reasoning_tokens=(
                    self._usage.token_usage.reasoning_tokens + usage.reasoning_tokens
                ),
                cached_input_tokens=(
                    self._usage.token_usage.cached_input_tokens + usage.cached_input_tokens
                ),
            ),
            estimated_cost_usd=round(self._usage.estimated_cost_usd + call_cost, 12),
        )
        self._usage = next_usage
        return self._check(next_usage, preflight=False)

    def _check(self, usage: GlobalBudgetUsage, *, preflight: bool) -> GlobalBudgetCheck:
        violations = self._violations(usage, preflight=preflight)
        check = GlobalBudgetCheck(
            usage=usage,
            within_budget=not violations,
            violations=tuple(violations),
        )
        if violations and self.policy.on_budget_exceeded == "fail":
            raise GlobalBudgetExceededError(check)
        return check

    def _violations(self, usage: GlobalBudgetUsage, *, preflight: bool) -> list[str]:
        violations: list[str] = []
        if self.policy.max_llm_calls is not None and usage.llm_calls > self.policy.max_llm_calls:
            violations.append("max_llm_calls")
        if not preflight:
            if (
                self.policy.max_total_tokens is not None
                and usage.token_usage.total_tokens > self.policy.max_total_tokens
            ):
                violations.append("max_total_tokens")
            if (
                self.policy.max_total_cost_usd is not None
                and usage.estimated_cost_usd > self.policy.max_total_cost_usd
            ):
                violations.append("max_total_cost_usd")
        return violations


def _component_cost(tokens: int, usd_per_1m_tokens: float | None) -> float:
    if usd_per_1m_tokens is None:
        return 0.0
    return tokens * usd_per_1m_tokens / 1_000_000


def _non_negative_token_estimate(value: int | None) -> int:
    if value is None:
        return 0
    parsed = int(value)
    if parsed < 0:
        raise ValueError("estimated prompt tokens must be non-negative")
    return parsed
