from __future__ import annotations

from framework.scoring import (
    BordaFusion,
    RankingItem,
    RankingResult,
    ReciprocalRankFusion,
    ScoreBundle,
    ScoringContext,
    ScoringRecipe,
    ScoringResult,
    WeightedScoreFusion,
)


def test_rrf_fuses_two_rankings() -> None:
    fused = ReciprocalRankFusion().fuse(
        [_ranking("r1", ["a", "b"]), _ranking("r2", ["b", "a"])],
        recipe=_recipe(),
        context=ScoringContext(),
    )

    assert {item.target_id for item in fused.items} == {"a", "b"}
    assert fused.items[0].score > 0


def test_borda_outputs_stable_order() -> None:
    fused = BordaFusion().fuse(
        [_ranking("r1", ["a", "b", "c"]), _ranking("r2", ["a", "c", "b"])],
        recipe=_recipe(),
        context=ScoringContext(),
    )

    assert [item.target_id for item in fused.items] == ["a", "b", "c"]


def test_weighted_score_fusion_uses_ranking_weights() -> None:
    fused = WeightedScoreFusion().fuse(
        [_ranking("r1", ["a", "b"]), _ranking("r2", ["b", "a"])],
        recipe=ScoringRecipe(
            recipe_id="fusion",
            version="1.0",
            target_type="board_card",
            scorers=["weighted_linear"],
            params={"ranking_weights": {"r2": 10.0}},
        ),
        context=ScoringContext(),
    )

    assert fused.items[0].target_id == "b"


def _recipe() -> ScoringRecipe:
    return ScoringRecipe(recipe_id="fusion", version="1.0", target_type="board_card", scorers=["weighted_linear"])


def _ranking(recipe_id: str, target_ids: list[str]) -> RankingResult:
    items = []
    for rank, target_id in enumerate(target_ids, start=1):
        score = 1.0 / rank
        result = ScoringResult(
            target_id=target_id,
            target_type="board_card",
            recipe_id=recipe_id,
            score=ScoreBundle(raw_score=score, gated_score=score, calibrated_score=score, final_score=score),
        )
        items.append(RankingItem(target_id=target_id, target_type="board_card", rank=rank, score=score, result=result))
    return RankingResult(recipe_id=recipe_id, items=items)
