from __future__ import annotations

from framework.scoring.core import (
    ScoreBundle,
    ScoringContext,
    ScoringRecipeError,
    ScoringRegistryError,
    ScoringResult,
)
from framework.scoring.recipes import ScoringRecipe


def test_score_bundle_and_result_helpers_are_immutable() -> None:
    bundle = ScoreBundle.from_raw_score(1.5, confidence=0.4).with_gated_score(0.6).with_calibrated_score(0.7)
    result = ScoringResult(
        target_id="target",
        target_type="thing",
        recipe_id="recipe",
        score=bundle,
    ).with_explanation("ready")

    assert bundle.raw_score == 1.0
    assert bundle.gated_score == 0.6
    assert bundle.final_score == 0.7
    assert result.explanation == "ready"
    assert result.final_score == 0.7


def test_context_with_recipe_accepts_recipe_or_id() -> None:
    recipe = ScoringRecipe(recipe_id="recipe-a", version="1", target_type="thing", scorers=["weighted_linear"])

    assert ScoringContext(run_id="run").with_recipe(recipe).recipe_id == "recipe-a"
    assert ScoringContext(run_id="run").with_recipe("recipe-b").recipe_id == "recipe-b"


def test_scoring_error_types_are_available() -> None:
    assert issubclass(ScoringRecipeError, Exception)
    assert issubclass(ScoringRegistryError, Exception)
