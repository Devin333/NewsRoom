from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BudgetMode = Literal["fail", "fallback", "ask_approval", "warn"]


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

