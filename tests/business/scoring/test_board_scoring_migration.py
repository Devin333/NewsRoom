from __future__ import annotations

from business.boards.ai_news.ranking_rules import AI_NEWS_PROFILE
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
from business.scoring import (
    BoardScoringService,
    ai_news_feature_vector,
    ai_news_scoring_recipe,
    apply_scoring_result_to_board_card,
    board_card_feature_vector,
    board_card_scoring_target,
)
from framework.scoring import ScoreBundle, ScoreFactor, ScoringResult


def test_board_card_adapter_converts_card_features_and_result() -> None:
    card = _card()
    target = board_card_scoring_target(card)
    vector = board_card_feature_vector(card, features={"freshness": 0.8})
    result = ScoringResult(
        target_id=card.card_id,
        target_type="board_card",
        recipe_id="recipe",
        score=ScoreBundle.from_raw_score(
            0.8,
            factors=[ScoreFactor(name="freshness", value=0.8, weight=1.0)],
        ),
        explanation="migration explanation",
    )

    updated = apply_scoring_result_to_board_card(card, result, profile=AI_NEWS_PROFILE, policy=_policy())

    assert target.target_id == card.card_id
    assert vector.get("freshness") == 0.8
    assert updated.score.value == 0.8
    assert updated.ranking_features["scoring_recipe_id"] == "recipe"


def test_ai_news_feature_builder_and_recipe() -> None:
    vector = ai_news_feature_vector(_card())
    recipe = ai_news_scoring_recipe()

    assert set(AI_NEWS_PROFILE.feature_weights).issubset(vector.values)
    assert recipe.recipe_id == "ai_news_board_scoring_v1"


def test_board_scoring_service_scores_without_switching_board_flow() -> None:
    card = _card()
    service = BoardScoringService()

    scored = service.score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )

    assert scored.card_id == card.card_id
    assert scored.metadata["scoring_runtime"]["recipe_id"] == "ai_news_board_scoring_v1"
    assert scored.score.value >= 0.0


def _policy() -> BusinessPolicyProfile:
    return BusinessPolicyProfile(
        profile_id="policy",
        profile_type="board",
        version="1.0",
        name="Board policy",
    )


def _card() -> BoardCard:
    return BoardCard(
        card_id="card-1",
        board_type=BoardType.AI_NEWS,
        title="OpenAI launches agent memory",
        summary="OpenAI announces a new agent memory API for enterprise adoption.",
        primary_object_ref=ObjectRef(object_type=ObjectType.NEWS_ITEM, object_id="news-1"),
        score=Score(value=0.5),
        confidence=Confidence(value=0.7),
        evidence_refs=[
            SourceRef(
                source_name="OpenAI Blog",
                source_type=SourceType.OFFICIAL_BLOG,
                source_id="src-1",
                reliability=SourceReliability.OFFICIAL,
                url="https://example.com/news",
            )
        ],
    )
