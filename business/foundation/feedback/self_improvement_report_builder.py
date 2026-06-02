from __future__ import annotations

from typing import Any

from business.foundation.feedback.self_improvement_report import SelfImprovementReport


class SelfImprovementReportBuilder:
    def build(
        self,
        *,
        feedback_events: list[Any],
        learning_signals: list[Any],
        recommendations: list[Any],
        proposals: list[Any],
        measurement: Any,
        applied_policy_experiments: list[dict[str, Any]] | None = None,
        applied_overrides: list[dict[str, Any]] | None = None,
    ) -> SelfImprovementReport:
        policy_experiments = _resolved_policy_experiments(
            applied_policy_experiments=applied_policy_experiments,
            applied_overrides=applied_overrides,
        )
        compatibility_overrides = list(applied_overrides) if applied_overrides is not None else list(policy_experiments)
        return SelfImprovementReport(
            feedback_events=[_to_dict(event) for event in feedback_events],
            learning_signals=[_to_dict(signal) for signal in learning_signals],
            recommendations=[_to_dict(recommendation) for recommendation in recommendations],
            proposals=[_to_dict(proposal) for proposal in proposals],
            applied_policy_experiments=policy_experiments,
            applied_overrides=compatibility_overrides,
            measurement=_to_dict(measurement),
            risks=risk_notes_from_proposals(proposals),
            next_actions=next_actions_for_proposals(proposals),
        )


def risk_notes_from_proposals(proposals: list[Any]) -> list[str]:
    risks = []
    for proposal in proposals:
        proposal_id = str(getattr(proposal, "proposal_id", "proposal"))
        risk_level = str(getattr(proposal, "risk_level", ""))
        if risk_level in {"high", "critical"}:
            risks.append(f"{proposal_id}:{risk_level}")
    return risks


def next_actions_for_proposals(proposals: list[Any]) -> list[str]:
    return ["review proposed improvements"] if proposals else ["continue monitoring"]


def _resolved_policy_experiments(
    *,
    applied_policy_experiments: list[dict[str, Any]] | None,
    applied_overrides: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if applied_policy_experiments is not None:
        return [dict(item) for item in applied_policy_experiments]
    return [dict(item) for item in (applied_overrides or [])]


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value or {})
    except (TypeError, ValueError):
        return {"value": value}


__all__ = [
    "SelfImprovementReportBuilder",
    "next_actions_for_proposals",
    "risk_notes_from_proposals",
]
