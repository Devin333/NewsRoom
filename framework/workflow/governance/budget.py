from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "token_usage": self.token_usage.to_dict(),
            "estimated_cost_usd": self.estimated_cost_usd,
        }


class GlobalBudgetTracker:
    def __init__(self, policy: GlobalBudgetPolicy) -> None:
        self.policy = policy
        self._usage = GlobalBudgetUsage()

    @property
    def usage(self) -> GlobalBudgetUsage:
        return self._usage

    def snapshot(self) -> dict[str, Any]:
        return to_jsonable(self._usage.to_dict())

    def record_llm_call(
        self,
        usage: TokenUsage,
        pricing: Any | None = None,
        *,
        estimated_cost_usd: float | None = None,
        replace_reserved_prompt_tokens: int | None = None,
        count_request: bool = True,
    ) -> Any:
        _ = pricing
        reserved_prompt_tokens = max(0, int(replace_reserved_prompt_tokens or 0))
        self._usage = GlobalBudgetUsage(
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
            estimated_cost_usd=round(
                self._usage.estimated_cost_usd
                + float(
                    estimated_cost_usd
                    if estimated_cost_usd is not None
                    else usage.estimated_cost_usd or 0.0
                ),
                12,
            ),
        )
        return self.snapshot()


@dataclass(frozen=True)
class WorkflowBudgetPolicy:
    max_total_tokens: int | None = None
    max_total_cost_usd: float | None = None
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_wall_time_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "max_total_tokens",
            "max_total_cost_usd",
            "max_llm_calls",
            "max_tool_calls",
            "max_wall_time_seconds",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative when set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_total_tokens": self.max_total_tokens,
            "max_total_cost_usd": self.max_total_cost_usd,
            "max_llm_calls": self.max_llm_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_wall_time_seconds": self.max_wall_time_seconds,
        }

    def to_global_budget_policy(self) -> GlobalBudgetPolicy:
        return GlobalBudgetPolicy(
            max_total_cost_usd=self.max_total_cost_usd,
            max_total_tokens=self.max_total_tokens,
            max_llm_calls=self.max_llm_calls,
            on_budget_exceeded="warn",
        )


@dataclass
class WorkflowBudgetUsage:
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    wall_time_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "wall_time_seconds": self.wall_time_seconds,
        }


@dataclass(frozen=True)
class BudgetCheckResult:
    exceeded: bool
    exceeded_reason: str | None
    violations: list[str]
    usage: WorkflowBudgetUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "exceeded": self.exceeded,
            "exceeded_reason": self.exceeded_reason,
            "violations": list(self.violations),
            "usage": self.usage.to_dict(),
        }


class WorkflowBudgetTracker:
    def __init__(
        self,
        policy: WorkflowBudgetPolicy | None = None,
        *,
        global_budget_tracker: GlobalBudgetTracker | None = None,
    ) -> None:
        self.policy = policy or WorkflowBudgetPolicy()
        self._global_tracker = global_budget_tracker or GlobalBudgetTracker(
            self.policy.to_global_budget_policy()
        )
        self._tool_calls = 0
        self._started = perf_counter()

    @property
    def global_budget_tracker(self) -> GlobalBudgetTracker:
        return self._global_tracker

    def record_llm_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cached_input_tokens: int = 0,
        estimated_cost_usd: float | None = None,
    ) -> BudgetCheckResult:
        self._global_tracker.record_llm_call(
            TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                cached_input_tokens=cached_input_tokens,
            ),
            estimated_cost_usd=estimated_cost_usd,
        )
        return self.check()

    def record_tool_call(self, count: int = 1) -> BudgetCheckResult:
        self._tool_calls += max(0, int(count))
        return self.check()

    def record_wall_time(self, seconds: float | None = None) -> BudgetCheckResult:
        _ = seconds
        return self.check()

    def usage(self) -> WorkflowBudgetUsage:
        return budget_usage_from_snapshot(
            self._global_tracker.snapshot(),
            tool_calls=self._tool_calls,
            wall_time_seconds=perf_counter() - self._started,
        )

    def check(self) -> BudgetCheckResult:
        usage = self.usage()
        violations = budget_violations(self.policy, usage)
        return BudgetCheckResult(
            exceeded=bool(violations),
            exceeded_reason=violations[0] if violations else None,
            violations=violations,
            usage=usage,
        )

    def summary(self) -> dict[str, Any]:
        return budget_summary_from_usage(
            self.usage(),
            check=self.check(),
        )


def budget_usage_from_snapshot(
    snapshot: dict[str, Any],
    *,
    tool_calls: int = 0,
    wall_time_seconds: float = 0.0,
) -> WorkflowBudgetUsage:
    token_usage = snapshot.get("token_usage") if isinstance(snapshot, dict) else {}
    if not isinstance(token_usage, dict):
        token_usage = {}
    total_tokens = int(
        token_usage.get("total_tokens")
        or (
            int(token_usage.get("input_tokens") or 0)
            + int(token_usage.get("output_tokens") or 0)
            + int(token_usage.get("reasoning_tokens") or 0)
        )
    )
    return WorkflowBudgetUsage(
        total_tokens=total_tokens,
        total_cost_usd=float(snapshot.get("estimated_cost_usd") or 0.0),
        llm_calls=int(snapshot.get("llm_calls") or 0),
        tool_calls=int(snapshot.get("tool_calls") or tool_calls),
        wall_time_seconds=float(snapshot.get("wall_time_seconds") or wall_time_seconds),
    )


def budget_violations(
    policy: WorkflowBudgetPolicy,
    usage: WorkflowBudgetUsage,
) -> list[str]:
    violations: list[str] = []
    if policy.max_total_tokens is not None and usage.total_tokens > policy.max_total_tokens:
        violations.append("max_total_tokens")
    if (
        policy.max_total_cost_usd is not None
        and usage.total_cost_usd > policy.max_total_cost_usd
    ):
        violations.append("max_total_cost_usd")
    if policy.max_llm_calls is not None and usage.llm_calls > policy.max_llm_calls:
        violations.append("max_llm_calls")
    if policy.max_tool_calls is not None and usage.tool_calls > policy.max_tool_calls:
        violations.append("max_tool_calls")
    if (
        policy.max_wall_time_seconds is not None
        and usage.wall_time_seconds > policy.max_wall_time_seconds
    ):
        violations.append("max_wall_time_seconds")
    return violations


def budget_summary_from_usage(
    usage: WorkflowBudgetUsage,
    *,
    check: BudgetCheckResult | None = None,
) -> dict[str, Any]:
    exceeded = bool(check and check.exceeded)
    exceeded_reason = check.exceeded_reason if check else None
    return {
        "total_tokens": usage.total_tokens,
        "total_cost_usd": usage.total_cost_usd,
        "llm_calls": usage.llm_calls,
        "tool_calls": usage.tool_calls,
        "wall_time_seconds": usage.wall_time_seconds,
        "exceeded": exceeded,
        "exceeded_reason": exceeded_reason,
    }


def budget_summary_from_tracker(global_budget_tracker: Any | None) -> dict[str, Any] | None:
    if global_budget_tracker is None or not hasattr(global_budget_tracker, "snapshot"):
        return None
    snapshot = global_budget_tracker.snapshot()
    if not isinstance(snapshot, dict):
        return None
    usage = budget_usage_from_snapshot(snapshot)
    policy = _workflow_budget_policy_from_global_tracker(global_budget_tracker)
    check = BudgetCheckResult(
        exceeded=False,
        exceeded_reason=None,
        violations=[],
        usage=usage,
    )
    if policy is not None:
        violations = budget_violations(policy, usage)
        check = BudgetCheckResult(
            exceeded=bool(violations),
            exceeded_reason=violations[0] if violations else None,
            violations=violations,
            usage=usage,
        )
    return budget_summary_from_usage(usage, check=check)


def restore_global_budget_tracker_usage(
    global_budget_tracker: Any | None,
    snapshot: dict[str, Any] | None,
) -> bool:
    if global_budget_tracker is None or not isinstance(snapshot, dict):
        return False
    if not hasattr(global_budget_tracker, "_usage"):
        return False
    token_usage = snapshot.get("token_usage")
    if not isinstance(token_usage, dict):
        token_usage = {}
    global_budget_tracker._usage = GlobalBudgetUsage(
        llm_calls=int(snapshot.get("llm_calls") or 0),
        token_usage=TokenUsage(
            input_tokens=int(token_usage.get("input_tokens") or 0),
            output_tokens=int(token_usage.get("output_tokens") or 0),
            reasoning_tokens=int(token_usage.get("reasoning_tokens") or 0),
            cached_input_tokens=int(token_usage.get("cached_input_tokens") or 0),
        ),
        estimated_cost_usd=float(snapshot.get("estimated_cost_usd") or 0.0),
    )
    return True


def _workflow_budget_policy_from_global_tracker(
    global_budget_tracker: Any,
) -> WorkflowBudgetPolicy | None:
    policy = getattr(global_budget_tracker, "policy", None)
    if policy is None:
        return None
    return WorkflowBudgetPolicy(
        max_total_tokens=getattr(policy, "max_total_tokens", None),
        max_total_cost_usd=getattr(policy, "max_total_cost_usd", None),
        max_llm_calls=getattr(policy, "max_llm_calls", None),
    )



