from __future__ import annotations

from framework.scoring import (
    CompositeScoringAlgorithm,
    FeatureVector,
    ScoringContext,
    ScoringRecipe,
    ScoringTarget,
    WeightedScorer,
    WeightedScoringAlgorithm,
)


def test_algorithm_names_and_scorer_aliases_score() -> None:
    recipe = ScoringRecipe(
        recipe_id="recipe",
        version="1",
        target_type="thing",
        scorers=["weighted_linear"],
        weights={"score": 1.0},
    )
    target = ScoringTarget(target_id="a", target_type="thing")
    features = FeatureVector.from_scores({"score": 0.8})

    assert WeightedScorer is WeightedScoringAlgorithm
    assert WeightedScoringAlgorithm().score(target=target, features=features, recipe=recipe, context=ScoringContext()).final_score == 0.8


def test_composite_algorithm_combines_children() -> None:
    recipe = ScoringRecipe(
        recipe_id="recipe",
        version="1",
        target_type="thing",
        scorers=["composite"],
        weights={"score": 1.0},
    )
    algorithm = CompositeScoringAlgorithm(algorithms=(WeightedScoringAlgorithm(),))

    result = algorithm.score(
        target=ScoringTarget(target_id="a", target_type="thing"),
        features=FeatureVector.from_scores({"score": 0.7}),
        recipe=recipe,
        context=ScoringContext(),
    )

    assert result.final_score == 0.7
