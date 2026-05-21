from __future__ import annotations

from framework.scoring import (
    RankingItem,
    RankingResult,
    ScoreBundle,
    ScoreFactor,
    ScoreLevel,
    ScoreValue,
    ScoringResult,
)


def test_score_value_clamps_and_derives_level() -> None:
    assert ScoreValue.from_raw(1.5).value == 1.0
    assert ScoreValue.from_raw(-0.2).value == 0.0
    assert ScoreValue.from_raw(0.82).level == ScoreLevel.VERY_HIGH


def test_score_level_thresholds() -> None:
    assert ScoreLevel.from_score(0.0) == ScoreLevel.VERY_LOW
    assert ScoreLevel.from_score(0.2) == ScoreLevel.LOW
    assert ScoreLevel.from_score(0.4) == ScoreLevel.MEDIUM
    assert ScoreLevel.from_score(0.6) == ScoreLevel.HIGH
    assert ScoreLevel.from_score(0.8) == ScoreLevel.VERY_HIGH
    assert ScoreLevel.from_score(0.9, blocked=True) == ScoreLevel.BLOCKED


def test_score_factor_contribution_and_validation() -> None:
    factor = ScoreFactor(name="freshness", value=1.5, weight=0.25)

    assert factor.value == 1.0
    assert factor.contribution == 0.25


def test_score_bundle_round_trips() -> None:
    bundle = ScoreBundle(
        raw_score=1.2,
        gated_score=0.9,
        calibrated_score=0.8,
        final_score=0.7,
        confidence=0.6,
        factors=[ScoreFactor(name="evidence", value=0.8, weight=1.0)],
    )

    restored = ScoreBundle.from_dict(bundle.to_dict())

    assert restored == bundle
    assert restored.raw_score == 1.0
    assert restored.level == ScoreLevel.HIGH


def test_scoring_and_ranking_result_round_trip() -> None:
    result = ScoringResult(
        target_id="card-1",
        target_type="board_card",
        recipe_id="recipe",
        score=ScoreBundle(raw_score=0.7, gated_score=0.7, calibrated_score=0.7, final_score=0.7),
    )
    ranking = RankingResult(
        recipe_id="recipe",
        items=[RankingItem(target_id="card-1", target_type="board_card", rank=1, score=0.7, result=result)],
    )

    assert result.final_score == 0.7
    assert RankingResult.from_dict(ranking.to_dict()).items[0].result.final_score == 0.7
