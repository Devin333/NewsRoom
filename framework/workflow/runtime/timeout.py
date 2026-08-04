from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.specs import WorkflowSpec


@dataclass(frozen=True)
class WorkflowTimeoutBudget:
    timeout_seconds: float
    policy_source: str
    started_monotonic: float

    @property
    def deadline_monotonic(self) -> float:
        return self.started_monotonic + self.timeout_seconds

    def elapsed_seconds(self, now_monotonic: float) -> float:
        return max(0.0, now_monotonic - self.started_monotonic)

    def remaining_seconds(self, now_monotonic: float) -> float:
        return self.deadline_monotonic - now_monotonic

    def is_exceeded(self, now_monotonic: float) -> bool:
        return self.remaining_seconds(now_monotonic) <= 0

    def details(self, now_monotonic: float) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "elapsed_seconds": round(self.elapsed_seconds(now_monotonic), 6),
            "policy_source": self.policy_source,
            "started_monotonic": self.started_monotonic,
            "deadline_monotonic": self.deadline_monotonic,
        }


def workflow_timeout_budget(
    workflow: WorkflowSpec,
    *,
    started_monotonic: float,
    reserve_seconds: float = 0.0,
) -> WorkflowTimeoutBudget | None:
    candidates: list[tuple[str, float]] = []
    timeout_seconds = workflow.policies.timeout_policy.timeout_seconds
    if timeout_seconds is not None:
        candidates.append(("policies.timeout_policy.timeout_seconds", float(timeout_seconds)))
    max_runtime_seconds = workflow.policies.resource_policy.max_runtime_seconds
    if max_runtime_seconds is not None:
        candidates.append(("policies.resource_policy.max_runtime_seconds", float(max_runtime_seconds)))
    if not candidates:
        return None
    policy_source, seconds = min(candidates, key=lambda item: item[1])
    if reserve_seconds < 0:
        raise ValueError("reserve_seconds must be non-negative")
    effective_seconds = seconds - float(reserve_seconds)
    if effective_seconds <= 0:
        raise ValueError(
            "workflow timeout must leave a positive execution window after reserves"
        )
    return WorkflowTimeoutBudget(
        timeout_seconds=effective_seconds,
        policy_source=policy_source,
        started_monotonic=started_monotonic,
    )
