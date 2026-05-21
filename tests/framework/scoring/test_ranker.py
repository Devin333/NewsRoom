from __future__ import annotations

from framework.scoring import (
    DedupRanker,
    DiversityRanker,
    PriorityRanker,
    ScoreBundle,
    ScoringContext,
    ScoringRecipe,
    ScoringResult,
)


def test_priority_ranker_sorts_and_drops_blocked_items() -> None:
    ranking = PriorityRanker().rank(
        [_result("b", 0.7), _result("a", 0.9), _result("blocked", 1.0, blocked=True)],
        recipe=_recipe(),
        context=ScoringContext(),
    )

    assert [item.target_id for item in ranking.items] == ["a", "b"]
    assert [item.target_id for item in ranking.dropped_items] == ["blocked"]


def test_dedup_ranker_keeps_highest_score_for_key() -> None:
    ranking = DedupRanker().rank(
        [
            _result("a-low", 0.2, metadata={"canonical_id": "same"}),
            _result("a-high", 0.8, metadata={"canonical_id": "same"}),
            _result("b", 0.7, metadata={"canonical_id": "other"}),
        ],
        recipe=_recipe(),
        context=ScoringContext(),
    )

    assert [item.target_id for item in ranking.items] == ["a-high", "b"]
    assert [item.target_id for item in ranking.dropped_items] == ["a-low"]


def test_diversity_ranker_limits_same_source() -> None:
    ranking = DiversityRanker().rank(
        [
            _result("a", 0.9, metadata={"source": "same"}),
            _result("b", 0.8, metadata={"source": "same"}),
            _result("c", 0.7, metadata={"source": "same"}),
        ],
        recipe=ScoringRecipe(
            recipe_id="recipe",
            version="1.0",
            target_type="board_card",
            scorers=["weighted_linear"],
            params={"max_per_diversity_key": 2},
        ),
        context=ScoringContext(),
    )

    assert [item.target_id for item in ranking.items] == ["a", "b"]
    assert [item.target_id for item in ranking.dropped_items] == ["c"]


def _recipe() -> ScoringRecipe:
    return ScoringRecipe(recipe_id="recipe", version="1.0", target_type="board_card", scorers=["weighted_linear"])


def _result(target_id: str, score: float, *, blocked: bool = False, metadata: dict[str, object] | None = None) -> ScoringResult:
    return ScoringResult(
        target_id=target_id,
        target_type="board_card",
        recipe_id="recipe",
        score=ScoreBundle(raw_score=score, gated_score=score, calibrated_score=score, final_score=score, confidence=score),
        blocked=blocked,
        metadata=dict(metadata or {}),
    )
