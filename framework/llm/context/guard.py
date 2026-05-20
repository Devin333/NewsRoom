from __future__ import annotations

from dataclasses import dataclass

from framework.llm.context.estimator import estimate_request_tokens
from framework.llm.context.window import ContextPolicy, ContextStrategy
from framework.llm.models.request import LLMRequest


@dataclass(frozen=True)
class LLMContextCheck:
    estimated_input_tokens: int
    reserve_output_tokens: int
    projected_total_tokens: int
    max_context_tokens: int
    within_context: bool
    truncate_strategy: ContextStrategy

    def to_dict(self) -> dict[str, int | bool | str]:
        return {
            "estimated_input_tokens": self.estimated_input_tokens,
            "reserve_output_tokens": self.reserve_output_tokens,
            "projected_total_tokens": self.projected_total_tokens,
            "max_context_tokens": self.max_context_tokens,
            "within_context": self.within_context,
            "truncate_strategy": self.truncate_strategy,
        }


class LLMContextWindowExceededError(RuntimeError):
    def __init__(self, check: LLMContextCheck) -> None:
        super().__init__(
            "LLM context window exceeded: "
            f"{check.projected_total_tokens} > {check.max_context_tokens}"
        )
        self.check = check

    def to_dict(self) -> dict[str, object]:
        return {
            "message": str(self),
            "error_type": "context_length_exceeded",
            "context_check": self.check.to_dict(),
        }


class LLMContextGuard:
    def __init__(self, policy: ContextPolicy) -> None:
        self.policy = policy

    def check(self, request: LLMRequest, policy: ContextPolicy | None = None) -> LLMContextCheck:
        if policy is not None:
            return LLMContextGuard(policy).check_request(request)
        return self.check_request(request)

    def check_request(self, request: LLMRequest) -> LLMContextCheck:
        estimated_input_tokens = estimate_request_tokens(request)
        projected_total_tokens = estimated_input_tokens + self.policy.reserve_output_tokens
        check = LLMContextCheck(
            estimated_input_tokens=estimated_input_tokens,
            reserve_output_tokens=self.policy.reserve_output_tokens,
            projected_total_tokens=projected_total_tokens,
            max_context_tokens=self.policy.max_context_tokens,
            within_context=projected_total_tokens <= self.policy.max_context_tokens,
            truncate_strategy=self.policy.truncate_strategy,
        )
        if not check.within_context:
            raise LLMContextWindowExceededError(check)
        return check

