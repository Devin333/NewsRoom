from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any

from business.foundation.feedback.improvement_recommendation import ImprovementRecommendation
from business.foundation.feedback.policy_experiment import PolicyExperimentProfile
from business.foundation.feedback.proposal_builder import experiment_profile_for_recommendation


WEEKLY_INTELLIGENCE_BOARD_TYPE = "weekly_intelligence"


@dataclass(frozen=True)
class WeeklyPolicyExperimentRecommendation:
    recommendation: ImprovementRecommendation
    experiment_profile: PolicyExperimentProfile

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation.to_dict(),
            "policy_experiment_profile": self.experiment_profile.to_dict(),
        }


@dataclass(frozen=True)
class WeeklyImprovementReport:
    recommendations: list[WeeklyPolicyExperimentRecommendation] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendations": [item.recommendation.to_dict() for item in self.recommendations],
            "policy_experiment_profiles": [
                item.experiment_profile.to_dict()
                for item in self.recommendations
            ],
            "policy_experiment_profile_ids": [
                item.experiment_profile.profile_id
                for item in self.recommendations
            ],
            "risks": list(self.risks),
            "next_actions": list(self.next_actions),
        }


class WeeklyImprovementRecommendationService:
    def build(
        self,
        weekly_quality: dict[str, Any],
        weekly_trends: dict[str, Any],
    ) -> WeeklyImprovementReport:
        recommendations = self._recommendations_from_quality(weekly_quality)
        if not recommendations:
            recommendations = self._recommendations_from_trends(weekly_trends)
        return WeeklyImprovementReport(
            recommendations=recommendations,
            risks=_risks_for_recommendations(recommendations),
            next_actions=_next_actions_for_recommendations(recommendations),
        )

    def _recommendations_from_quality(
        self,
        weekly_quality: dict[str, Any],
    ) -> list[WeeklyPolicyExperimentRecommendation]:
        recommendations: list[WeeklyPolicyExperimentRecommendation] = []
        for weak_spot in weekly_quality.get("weak_spots") or []:
            weak_spot_id = str(weak_spot)
            recommendation = ImprovementRecommendation(
                recommendation_id=_stable_id("weekly", weak_spot_id),
                source="weekly_quality",
                board_type=WEEKLY_INTELLIGENCE_BOARD_TYPE,
                target_type="board_quality_gate",
                target_id=weak_spot_id,
                severity="warning",
                reason=f"Weekly quality weak spot: {weak_spot_id}",
                suggested_action="Evaluate a quality-gate policy experiment for source coverage and trend confidence thresholds.",
                evidence=[{"weak_spot": weak_spot_id}],
            )
            recommendations.append(_with_experiment_profile(recommendation))
        return recommendations

    def _recommendations_from_trends(
        self,
        weekly_trends: dict[str, Any],
    ) -> list[WeeklyPolicyExperimentRecommendation]:
        weak_signal_trends = _dict_list(weekly_trends.get("weak_signal_trends"))
        if not weak_signal_trends:
            return []
        recommendation = ImprovementRecommendation(
            recommendation_id=_stable_id("weekly", "weak_signal_review"),
            source="weekly_trend_analysis",
            board_type=WEEKLY_INTELLIGENCE_BOARD_TYPE,
            target_type="skill_prompt_hint",
            target_id="trend-analysis",
            severity="info",
            reason="Weekly run produced weak-signal trends that may need analyst review.",
            suggested_action="Evaluate a prompt-hint policy experiment for weak-signal trend synthesis.",
            evidence=weak_signal_trends,
        )
        return [_with_experiment_profile(recommendation)]


class WeeklyImprovementBuilder:
    def __init__(self, *, recommendation_service: WeeklyImprovementRecommendationService | None = None) -> None:
        self.recommendation_service = recommendation_service or WeeklyImprovementRecommendationService()

    def build(self, weekly_quality: dict[str, Any], weekly_trends: dict[str, Any]) -> dict[str, Any]:
        return self.recommendation_service.build(weekly_quality, weekly_trends).to_dict()


def _with_experiment_profile(
    recommendation: ImprovementRecommendation,
) -> WeeklyPolicyExperimentRecommendation:
    return WeeklyPolicyExperimentRecommendation(
        recommendation=recommendation,
        experiment_profile=experiment_profile_for_recommendation(recommendation),
    )


def _risks_for_recommendations(
    recommendations: list[WeeklyPolicyExperimentRecommendation],
) -> list[str]:
    if not recommendations:
        return []
    return ["manual approval required before policy experiment activation"]


def _next_actions_for_recommendations(
    recommendations: list[WeeklyPolicyExperimentRecommendation],
) -> list[str]:
    if not recommendations:
        return ["continue monitoring"]
    return ["review weekly policy experiment recommendations"]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(dict(item))
        else:
            result.append({"value": item})
    return result


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{sha1(value.encode('utf-8')).hexdigest()[:12]}"


__all__ = [
    "WEEKLY_INTELLIGENCE_BOARD_TYPE",
    "WeeklyImprovementBuilder",
    "WeeklyImprovementRecommendationService",
    "WeeklyImprovementReport",
    "WeeklyPolicyExperimentRecommendation",
]
