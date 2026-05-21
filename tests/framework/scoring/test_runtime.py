from __future__ import annotations

from framework.scoring import (
    FeatureVector,
    RankingResult,
    ScoringRecipe,
    ScoringRuntime,
    ScoringTarget,
)


def test_score_object_runs_scorer_gate_and_explanation() -> None:
    result = ScoringRuntime().score_object(
        _target("card-1"),
        features=FeatureVector.from_scores({"evidence": 1.0, "freshness": 0.8}),
        recipe=ScoringRecipe(
            recipe_id="recipe",
            version="1.0",
            target_type="board_card",
            gates=["requires_evidence"],
            scorers=["weighted_linear"],
            weights={"evidence": 0.75, "freshness": 0.25},
            explainer="template",
            params={
                "gate_specs": {
                    "requires_evidence": {
                        "action": "block",
                        "feature": "evidence",
                        "operator": "exists",
                    }
                }
            },
        ),
    )

    assert result.final_score == 0.95
    assert result.explanation
    assert [step.step_type for step in result.trace.steps] == ["gate", "scorer", "gate_application", "calibrator", "explainer"]


def test_block_gate_sets_final_score_to_zero() -> None:
    result = ScoringRuntime().score_object(
        _target("card-1"),
        features=FeatureVector.from_scores({"freshness": 1.0}),
        recipe=_gated_recipe({"action": "block", "feature": "evidence", "operator": "exists"}),
    )

    assert result.blocked is True
    assert result.final_score == 0.0


def test_cap_gate_limits_final_score() -> None:
    result = ScoringRuntime().score_object(
        _target("card-1"),
        features=FeatureVector.from_scores({"score": 1.0}),
        recipe=_gated_recipe(
            {
                "action": "cap",
                "feature": "evidence",
                "operator": "exists",
                "score_cap": 0.4,
            },
        ),
    )

    assert result.final_score == 0.4


def test_rank_list_scores_and_sorts_targets() -> None:
    ranking = ScoringRuntime().rank_list(
        [_target("a"), _target("b")],
        feature_vectors={
            "a": FeatureVector.from_scores({"score": 0.2}),
            "b": FeatureVector.from_scores({"score": 0.9}),
        },
        recipe=ScoringRecipe(
            recipe_id="recipe",
            version="1.0",
            target_type="board_card",
            scorers=["weighted_linear"],
            weights={"score": 1.0},
        ),
    )

    assert [item.target_id for item in ranking.items] == ["b", "a"]


def test_score_path_requires_graph_path_scorer_and_scores_path() -> None:
    runtime = ScoringRuntime()
    recipe = ScoringRecipe(
        recipe_id="path",
        version="1.0",
        target_type="cross_board_path",
        scorers=["graph_path_score"],
        weights={"stage_completeness": 1.0},
    )

    result = runtime.score_path(
        ScoringTarget(target_id="path-1", target_type="cross_board_path"),
        features=FeatureVector.from_scores({"stage_completeness": 0.8}),
        recipe=recipe,
    )

    assert result.final_score == 0.8


def test_fuse_rankings_defaults_to_rrf() -> None:
    runtime = ScoringRuntime()
    base_recipe = ScoringRecipe(
        recipe_id="rank",
        version="1.0",
        target_type="board_card",
        scorers=["weighted_linear"],
        weights={"score": 1.0},
    )
    ranking_a = runtime.rank_list(
        [_target("a"), _target("b")],
        feature_vectors={
            "a": FeatureVector.from_scores({"score": 1.0}),
            "b": FeatureVector.from_scores({"score": 0.5}),
        },
        recipe=base_recipe,
    )
    ranking_b = runtime.rank_list(
        [_target("b"), _target("a")],
        feature_vectors={
            "a": FeatureVector.from_scores({"score": 0.5}),
            "b": FeatureVector.from_scores({"score": 1.0}),
        },
        recipe=base_recipe,
    )

    fused = runtime.fuse_rankings(
        [ranking_a, ranking_b],
        recipe=ScoringRecipe(recipe_id="fusion", version="1.0", target_type="board_card", scorers=["weighted_linear"]),
    )

    assert isinstance(fused, RankingResult)
    assert {item.target_id for item in fused.items} == {"a", "b"}


def _target(target_id: str) -> ScoringTarget:
    return ScoringTarget(target_id=target_id, target_type="board_card")


def _gated_recipe(gate_spec: dict[str, object]) -> ScoringRecipe:
    return ScoringRecipe(
        recipe_id="recipe",
        version="1.0",
        target_type="board_card",
        gates=["gate"],
        scorers=["weighted_linear"],
        weights={"score": 1.0},
        params={"gate_specs": {"gate": gate_spec}},
    )
