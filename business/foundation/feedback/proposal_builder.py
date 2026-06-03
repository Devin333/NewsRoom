from __future__ import annotations

from hashlib import sha1
from typing import Any

from business.foundation.feedback.improvement_proposal import ImprovementProposal
from business.foundation.feedback.improvement_recommendation import ImprovementRecommendation
from business.foundation.feedback.policy_experiment import (
    PolicyExperimentProfile,
    policy_experiment_profile_id,
    policy_experiment_target_type,
)


class ImprovementProposalBuilder:
    def build_from_recommendations(
        self,
        recommendations: list[ImprovementRecommendation],
    ) -> list[ImprovementProposal]:
        return [proposal_for_recommendation(recommendation) for recommendation in recommendations]


def proposal_for_recommendation(recommendation: ImprovementRecommendation) -> ImprovementProposal:
    target_type = policy_experiment_target_type(recommendation.target_type)
    experiment_profile = experiment_profile_for_recommendation(
        recommendation,
        target_type=target_type,
    )
    return ImprovementProposal(
        proposal_id=stable_proposal_id(recommendation, target_type=target_type),
        recommendation_id=recommendation.recommendation_id,
        board_type=recommendation.board_type,
        change_type="policy_experiment",
        target_type=target_type,
        target_id=recommendation.target_id,
        policy_experiment_parameters=experiment_profile.parameters,
        risk_level=risk_level_for_severity(recommendation.severity),
        requires_approval=True,
        status="proposed",
        experiment_profile=experiment_profile,
    )


def experiment_profile_for_recommendation(
    recommendation: ImprovementRecommendation,
    *,
    target_type: str | None = None,
) -> PolicyExperimentProfile:
    resolved_target_type = policy_experiment_target_type(target_type or recommendation.target_type)
    return PolicyExperimentProfile(
        profile_id=policy_experiment_profile_id(
            recommendation.board_type,
            recommendation.recommendation_id,
            resolved_target_type,
            recommendation.target_id,
        ),
        board_type=recommendation.board_type,
        target_type=resolved_target_type,
        target_id=recommendation.target_id,
        parameters={
            "severity": recommendation.severity,
            "evidence_count": len(recommendation.evidence),
        },
        rationale=recommendation.reason,
        suggested_action=recommendation.suggested_action,
    )


def risk_level_for_severity(severity: str) -> str:
    return {"block": "critical", "error": "high", "warning": "medium"}.get(severity, "low")


def stable_proposal_id(recommendation: ImprovementRecommendation, *, target_type: str | None = None) -> str:
    resolved_target_type = policy_experiment_target_type(target_type or recommendation.target_type)
    return _stable_id(
        "proposal",
        recommendation.recommendation_id,
        resolved_target_type,
        recommendation.target_id,
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


__all__ = [
    "ImprovementProposalBuilder",
    "experiment_profile_for_recommendation",
    "proposal_for_recommendation",
    "risk_level_for_severity",
    "stable_proposal_id",
]
