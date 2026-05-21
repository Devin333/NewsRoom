from __future__ import annotations

from framework.scoring import FeatureVector, ScoringRecipe, ScoringRuntime, ScoringTarget


def test_runtime_resolves_default_gate_specs_from_registry() -> None:
    result = ScoringRuntime().score_object(
        ScoringTarget(target_id="a", target_type="thing"),
        features=FeatureVector.from_scores({"score": 1.0}),
        recipe=ScoringRecipe(
            recipe_id="recipe",
            version="1",
            target_type="thing",
            gates=["score_cap_no_evidence"],
            scorers=["weighted_linear"],
            weights={"score": 1.0},
        ),
    )

    assert result.final_score == 0.35
    assert result.gates[0].gate_id == "score_cap_no_evidence"
