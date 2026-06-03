from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.foundation.feedback.improvement_recommendation import ImprovementRecommendation
from business.foundation.feedback.policy_experiment import PolicyExperimentProfile


@dataclass(frozen=True)
class PolicyExperimentRecommendation:
    recommendation: ImprovementRecommendation
    experiment_profile: PolicyExperimentProfile

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation.to_dict(),
            "policy_experiment_profile": self.experiment_profile.to_dict(),
        }


__all__ = ["PolicyExperimentRecommendation"]
