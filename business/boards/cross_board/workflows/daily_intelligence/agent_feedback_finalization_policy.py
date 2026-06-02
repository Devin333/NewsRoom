from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.foundation.value_normalization import list_value, to_plain_dict


@dataclass(frozen=True)
class AgentFeedbackFinalizationPolicyDecision:
    recommended_action: str | None = None
    recommendation: dict[str, Any] | None = None

    @property
    def should_apply(self) -> bool:
        return self.recommended_action is not None and self.recommendation is not None


def select_agent_feedback_finalization_policy(
    summary: Any,
    *,
    strict_gate_required: bool,
) -> AgentFeedbackFinalizationPolicyDecision:
    if not strict_gate_required:
        return AgentFeedbackFinalizationPolicyDecision()
    summary_payload = to_plain_dict(summary)
    recommendations = [
        to_plain_dict(recommendation)
        for recommendation in list_value(summary_payload.get("policy_recommendations"))
    ]
    for action in ("block", "human_review", "rewrite"):
        for recommendation in recommendations:
            if _recommendation_action(recommendation) == action:
                return AgentFeedbackFinalizationPolicyDecision(
                    recommended_action=action,
                    recommendation=recommendation,
                )
    return AgentFeedbackFinalizationPolicyDecision()


def _recommendation_action(recommendation: Mapping[str, Any]) -> str:
    return str(recommendation.get("recommended_action") or "").strip().lower()


__all__ = [
    "AgentFeedbackFinalizationPolicyDecision",
    "select_agent_feedback_finalization_policy",
]
