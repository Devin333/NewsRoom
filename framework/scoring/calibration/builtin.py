from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoringResult, clamp_score
from framework.scoring.recipes import ScoringRecipe


@dataclass(frozen=True)
class NoopCalibrator:
    calibrator_id: str = "noop"

    def calibrate(
        self,
        result: ScoringResult,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoringResult:
        return result


@dataclass(frozen=True)
class PolicyCalibrator:
    calibrator_id: str = "policy"
    policy_params: dict[str, Any] = field(default_factory=dict)

    def calibrate(
        self,
        result: ScoringResult,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoringResult:
        params = {**self.policy_params, **dict(recipe.params.get("policy_calibration") or {})}
        return _apply_calibration(result, params, calibrator_id=self.calibrator_id)


@dataclass(frozen=True)
class FeedbackCalibrator:
    calibrator_id: str = "feedback"
    feedback_adjustments: dict[str, float] = field(default_factory=dict)

    def calibrate(
        self,
        result: ScoringResult,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoringResult:
        params = {**self.feedback_adjustments, **dict(recipe.params.get("feedback_calibration") or {})}
        return _apply_calibration(result, params, calibrator_id=self.calibrator_id)


def _apply_calibration(
    result: ScoringResult,
    params: dict[str, Any],
    *,
    calibrator_id: str,
) -> ScoringResult:
    if not params:
        return result
    score = result.final_score
    if params.get("override") is not None:
        score = float(params["override"])
    if params.get("score_cap") is not None:
        score = min(score, float(params["score_cap"]))
    score -= float(params.get("penalty", 0.0))
    score += float(params.get("boost", 0.0))
    score = clamp_score(score)
    bundle = result.score.with_calibrated_score(score)
    bundle = replace(bundle, metadata={**bundle.metadata, "calibrator_id": calibrator_id})
    return replace(
        result,
        score=bundle,
        metadata={**result.metadata, "calibration": {"calibrator_id": calibrator_id, **params}},
    )
