from __future__ import annotations

from business.boards._intelligence import (
    BoardScoringProfile,
    apply_scoring_result_to_card,
    feature_vector_from_board_card,
    scoring_recipe_from_board_profile,
    scoring_target_from_board_card,
)
from business.foundation import (
    BoardCard,
    BoardType,
    BusinessPolicyProfile,
    Confidence,
    ObjectRef,
    ObjectType,
    Score,
    SourceRef,
    SourceReliability,
    SourceType,
)
from framework.scoring import ScoreBundle, ScoreFactor, ScoringResult


def test_board_scoring_profile_converts_to_scoring_recipe() -> None:
    recipe = scoring_recipe_from_board_profile(_profile())

    assert recipe.recipe_id == "ai_news_board_scoring_v1"
    assert recipe.target_type == "board_card"
    assert recipe.scorers == ["weighted_linear"]
    assert recipe.weights == {"freshness": 0.6, "evidence": 0.4}


def test_board_card_features_convert_to_feature_vector() -> None:
    card = _card()

    vector = feature_vector_from_board_card(card, features={"freshness": 0.8, "evidence": 1.0})

    assert vector.get("freshness") == 0.8
    assert vector.metadata["card_id"] == card.card_id
    assert vector.evidence_refs == ["src-1"]


def test_board_card_converts_to_scoring_target() -> None:
    target = scoring_target_from_board_card(_card())

    assert target.target_id == "card-1"
    assert target.target_type == "board_card"
    assert target.metadata["board_type"] == "ai_news"


def test_scoring_result_maps_back_to_board_card() -> None:
    result = ScoringResult(
        target_id="card-1",
        target_type="board_card",
        recipe_id="recipe",
        score=ScoreBundle(
            raw_score=0.8,
            gated_score=0.8,
            calibrated_score=0.8,
            final_score=0.8,
            factors=[ScoreFactor(name="freshness", value=0.8, weight=1.0)],
        ),
        explanation="framework explanation",
    )

    card = apply_scoring_result_to_card(
        _card(),
        result,
        profile=_profile(),
        policy=_policy(),
    )

    assert card.score.value == 0.8
    assert card.ranking_reason == "framework explanation"
    assert card.ranking_features["freshness"] == 0.8
    assert card.ranking_features["scoring_recipe_id"] == "recipe"
    assert card.metadata["scoring_runtime"]["final_score"] == 0.8


def _profile() -> BoardScoringProfile:
    return BoardScoringProfile(
        board_type=BoardType.AI_NEWS,
        focus="product_adoption_news",
        feature_weights={"freshness": 0.6, "evidence": 0.4},
        badge_rules=(),
        metric_labels={},
    )


def _policy() -> BusinessPolicyProfile:
    return BusinessPolicyProfile(
        profile_id="policy-1",
        profile_type="board",
        version="1.0",
        name="Board policy",
    )


def _card() -> BoardCard:
    return BoardCard(
        card_id="card-1",
        board_type=BoardType.AI_NEWS,
        title="Agent Memory update",
        summary="OpenAI launches agent memory.",
        primary_object_ref=ObjectRef(object_type=ObjectType.NEWS_ITEM, object_id="news-1"),
        score=Score(value=0.5),
        confidence=Confidence(value=0.7),
        evidence_refs=[
            SourceRef(
                source_name="OpenAI Blog",
                source_type=SourceType.RSS,
                source_id="src-1",
                reliability=SourceReliability.HIGH,
                url="https://example.com/news",
            )
        ],
    )
