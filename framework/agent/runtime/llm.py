from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.llm.models import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamAccumulator,
    LLMStreamEvent,
    LLMToolCall,
    TokenUsage,
)
from framework.llm.structured_output import (
    LLMStructuredOutputValidationError,
    validate_structured_output,
)


@dataclass(frozen=True)
class GlobalBudgetPolicy:
    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None
    max_llm_calls: int | None = None
    on_budget_exceeded: str = "fail"


@dataclass(frozen=True)
class GlobalBudgetUsage:
    llm_calls: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_usage", TokenUsage.from_any(self.token_usage))

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
    def __init__(self, check: Any) -> None:
        super().__init__("global budget exceeded: " + ", ".join(getattr(check, "violations", []) or []))
        self.check = check
        self.error_type = "global_budget_exceeded"


class GlobalBudgetTracker:
    def __init__(self, policy: GlobalBudgetPolicy) -> None:
        self.policy = policy
        self._usage = GlobalBudgetUsage()

    @property
    def usage(self) -> GlobalBudgetUsage:
        return self._usage

    def snapshot(self) -> dict[str, object]:
        return self._usage.to_dict()

    def check_before_llm_call(self, estimated_prompt_tokens: int | None = None) -> GlobalBudgetCheck:
        next_usage = self._preflight_usage(estimated_prompt_tokens=estimated_prompt_tokens)
        return self._check(next_usage, preflight=True)

    def reserve_llm_call(self, estimated_prompt_tokens: int | None = None) -> GlobalBudgetCheck:
        next_usage = self._preflight_usage(estimated_prompt_tokens=estimated_prompt_tokens)
        check = self._check(next_usage, preflight=True)
        self._usage = next_usage
        return check

    def record_llm_call(self, usage: Any, **_: Any) -> GlobalBudgetCheck:
        usage = TokenUsage.from_any(usage)
        next_usage = GlobalBudgetUsage(
            llm_calls=self._usage.llm_calls + 1,
            token_usage=TokenUsage(
                input_tokens=self._usage.token_usage.input_tokens + usage.input_tokens,
                output_tokens=self._usage.token_usage.output_tokens + usage.output_tokens,
                reasoning_tokens=self._usage.token_usage.reasoning_tokens + usage.reasoning_tokens,
                cached_input_tokens=self._usage.token_usage.cached_input_tokens + usage.cached_input_tokens,
            ),
            estimated_cost_usd=self._usage.estimated_cost_usd + float(usage.estimated_cost_usd or 0.0),
        )
        self._usage = next_usage
        return self._check(next_usage, preflight=False)

    def _preflight_usage(self, *, estimated_prompt_tokens: int | None) -> GlobalBudgetUsage:
        prompt_tokens = int(estimated_prompt_tokens or 0)
        return GlobalBudgetUsage(
            llm_calls=self._usage.llm_calls + 1,
            token_usage=TokenUsage(
                input_tokens=self._usage.token_usage.input_tokens + max(0, prompt_tokens),
                output_tokens=self._usage.token_usage.output_tokens,
                reasoning_tokens=self._usage.token_usage.reasoning_tokens,
                cached_input_tokens=self._usage.token_usage.cached_input_tokens,
            ),
            estimated_cost_usd=self._usage.estimated_cost_usd,
        )

    def _check(self, usage: GlobalBudgetUsage, *, preflight: bool) -> GlobalBudgetCheck:
        violations: list[str] = []
        if self.policy.max_llm_calls is not None and usage.llm_calls > self.policy.max_llm_calls:
            violations.append("max_llm_calls")
        if not preflight:
            if self.policy.max_total_tokens is not None and usage.token_usage.total_tokens > self.policy.max_total_tokens:
                violations.append("max_total_tokens")
            if self.policy.max_total_cost_usd is not None and usage.estimated_cost_usd > self.policy.max_total_cost_usd:
                violations.append("max_total_cost_usd")
        check = GlobalBudgetCheck(usage=usage, within_budget=not violations, violations=tuple(violations))
        if violations and self.policy.on_budget_exceeded == "fail":
            raise GlobalBudgetExceededError(check)
        return check


__all__ = [
    "GlobalBudgetCheck",
    "GlobalBudgetExceededError",
    "GlobalBudgetPolicy",
    "GlobalBudgetTracker",
    "GlobalBudgetUsage",
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamAccumulator",
    "LLMStreamEvent",
    "LLMStructuredOutputValidationError",
    "LLMToolCall",
    "TokenUsage",
    "validate_structured_output",
]
