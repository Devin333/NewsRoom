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
from business.memory import BusinessMemoryDecisionService, BusinessMemoryRecallService
from business.scoring import BoardScoringService, ai_news_feature_vector


def test_board_scoring_without_memory_service_stays_score_neutral() -> None:
    card = _card()
    service = BoardScoringService()

    scored = service.score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )

    assert scored.metadata["memory_features_used"] is False
    assert scored.metadata["scoring_runtime"]["recipe_id"] == "ai_news_board_scoring_v1"
    assert "memory_decision_score" not in scored.ranking_features


def test_unavailable_memory_service_does_not_change_board_score() -> None:
    card = _card()
    baseline = BoardScoringService().score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )
    with_empty_memory = BoardScoringService(
        memory_decision_service=BusinessMemoryDecisionService()
    ).score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )

    assert with_empty_memory.metadata["memory_features_used"] is False
    assert with_empty_memory.score.value == baseline.score.value


def test_positive_memory_features_can_lift_scoring() -> None:
    card = _card()
    baseline = BoardScoringService().score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )
    with_memory = BoardScoringService(
        memory_decision_service=_memory_service(
            [
                {
                    "document_id": "doc-1",
                    "score": 0.94,
                    "text": "OpenAI launches agent memory",
                    "source_name": "OpenAI Blog",
                    "published_at": "2026-05-20T00:00:00Z",
                    "metadata": {
                        "source_name": "OpenAI Blog",
                        "topic": "agents",
                        "confidence": 0.94,
                        "tags": ["reliable_source", "verified_evidence"],
                    },
                },
                {
                    "document_id": "doc-2",
                    "score": 0.86,
                    "text": "Enterprise teams adopt agent memory",
                    "source_name": "Microsoft",
                    "published_at": "2026-05-18T00:00:00Z",
                    "metadata": {"topic": "agents", "confidence": 0.86},
                },
            ]
        )
    ).score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )

    assert with_memory.metadata["memory_features_used"] is True
    assert with_memory.ranking_features["memory_decision_score"] > 0.5
    assert with_memory.score.value >= baseline.score.value


def test_duplicate_or_misrank_memory_features_lower_scoring() -> None:
    card = _card()
    baseline = BoardScoringService().score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )
    with_memory = BoardScoringService(
        memory_decision_service=_memory_service(
            [
                {
                    "document_id": "doc-1",
                    "score": 0.92,
                    "text": card.title,
                    "source_name": "OpenAI Blog",
                    "evidence_id": "src-1",
                    "source_item_id": "src-1",
                    "metadata": {
                        "topic": "agents",
                        "tags": [
                            "weak_evidence_ranked_too_high",
                            "community_noise_overranked",
                            "repeated_noise",
                        ],
                        "note": "noise",
                    },
                }
            ]
        )
    ).score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )

    assert with_memory.metadata["memory_features_used"] is True
    assert with_memory.ranking_features["historical_duplicate_score"] > 0.0
    assert with_memory.ranking_features["previous_misrank_penalty"] > 0.0
    assert with_memory.score.value < baseline.score.value


class _SearchPort:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results

    def search(self, **kwargs: object) -> list[dict[str, object]]:
        return list(self.results)


def _memory_service(results: list[dict[str, object]]) -> BusinessMemoryDecisionService:
    return BusinessMemoryDecisionService(BusinessMemoryRecallService(_SearchPort(results)))


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
