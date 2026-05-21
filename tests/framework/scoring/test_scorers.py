from __future__ import annotations

from framework.scoring import (
    BayesianScorer,
    FeatureVector,
    FreshnessDecayScorer,
    GraphPathScorer,
    ScoringContext,
    ScoringRecipe,
    ScoringTarget,
    WeightedScorer,
    WilsonScorer,
)


def test_weighted_scorer_uses_normalized_weights() -> None:
    bundle = WeightedScorer().score(
        target=_target(),
        features=FeatureVector.from_scores({"a": 1.0, "b": 0.0}),
        recipe=ScoringRecipe(
            recipe_id="recipe",
            version="1.0",
            target_type="board_card",
            scorers=["weighted_linear"],
            weights={"a": 3.0, "b": 1.0},
        ),
        context=ScoringContext(),
    )

    assert bundle.final_score == 0.75


def test_weighted_scorer_handles_empty_weights() -> None:
    bundle = WeightedScorer().score(
        target=_target(),
        features=FeatureVector.from_scores({"a": 1.0, "b": 0.0}),
        recipe=ScoringRecipe(
            recipe_id="recipe",
            version="1.0",
            target_type="board_card",
            scorers=["weighted_linear"],
        ),
        context=ScoringContext(),
    )

    assert bundle.final_score == 0.5


def test_wilson_scorer_is_conservative_for_small_samples() -> None:
    bundle = WilsonScorer().score(
        target=_target(),
        features=FeatureVector.from_scores({"positive_count": 1, "total_count": 1}),
        recipe=_recipe("wilson_score"),
        context=ScoringContext(),
    )

    assert 0.0 < bundle.final_score < 0.5


def test_bayesian_scorer_smooths_extreme_values() -> None:
    bundle = BayesianScorer().score(
        target=_target(),
        features=FeatureVector.from_scores({"value": 1.0, "count": 1}),
        recipe=_recipe("bayesian_smoothing"),
        context=ScoringContext(),
    )

    assert 0.5 < bundle.final_score < 1.0


def test_freshness_decay_decreases_with_age() -> None:
    fresh = FreshnessDecayScorer().score(
        target=_target(),
        features=FeatureVector.from_scores({"age_days": 0}),
        recipe=_recipe("freshness_decay"),
        context=ScoringContext(),
    )
    old = FreshnessDecayScorer().score(
        target=_target(),
        features=FeatureVector.from_scores({"age_days": 7}),
        recipe=_recipe("freshness_decay"),
        context=ScoringContext(),
    )

    assert fresh.final_score == 1.0
    assert old.final_score == 0.5


def test_graph_path_scorer_applies_contradiction_penalty() -> None:
    bundle = GraphPathScorer().score(
        target=ScoringTarget(target_id="path-1", target_type="cross_board_path"),
        features=FeatureVector.from_scores({"stage_completeness": 1.0, "contradiction_penalty": 0.2}),
        recipe=ScoringRecipe(
            recipe_id="path",
            version="1.0",
            target_type="cross_board_path",
            scorers=["graph_path_score"],
            weights={"stage_completeness": 1.0},
        ),
        context=ScoringContext(),
    )

    assert bundle.final_score == 0.8


def _target() -> ScoringTarget:
    return ScoringTarget(target_id="card-1", target_type="board_card")


def _recipe(scorer_id: str) -> ScoringRecipe:
    return ScoringRecipe(
        recipe_id="recipe",
        version="1.0",
        target_type="board_card",
        scorers=[scorer_id],
    )
