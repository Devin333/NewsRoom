from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SelfImprovementReport:
    feedback_events: list[dict[str, Any]] = field(default_factory=list)
    learning_signals: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    policy_experiment_profiles: list[dict[str, Any]] = field(default_factory=list)
    policy_experiment_profile_ids: list[str] = field(default_factory=list)
    applied_policy_experiments: list[dict[str, Any]] = field(default_factory=list)
    applied_overrides: list[dict[str, Any]] = field(default_factory=list)
    measurement: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["SelfImprovementReport"]
