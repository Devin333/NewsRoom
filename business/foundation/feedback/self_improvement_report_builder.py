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
        applied_overrides: list[dict[str, Any]],
        measurement: Any,
    ) -> SelfImprovementReport:
        return SelfImprovementReport(
            feedback_events=[_to_dict(event) for event in feedback_events],
            learning_signals=[_to_dict(signal) for signal in learning_signals],
            recommendations=[_to_dict(recommendation) for recommendation in recommendations],
            proposals=[_to_dict(proposal) for proposal in proposals],
            applied_overrides=list(applied_overrides),
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
