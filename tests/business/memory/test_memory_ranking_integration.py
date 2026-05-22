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
from business.memory.intelligence_models import DecisionMemory, EntityMemory, EventMemory
from business.scoring import BoardScoringService, ai_news_feature_vector


def test_board_ranking_uses_structured_memory_features_when_repository_is_injected() -> None:
    card = _card()
    baseline = BoardScoringService(
        memory_decision_service=BusinessMemoryDecisionService(BusinessMemoryRecallService(_SearchPort()))
    ).score_card(
        card,
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )
    scored = BoardScoringService(
        memory_decision_service=BusinessMemoryDecisionService(
            BusinessMemoryRecallService(_SearchPort()),
            intelligence_repository=_StructuredMemoryRepository(),
        )
    ).score_card(
        card.model_copy(update={"metadata": {"topic": "agents", "entity_ids": ["entity-openai"]}}),
        profile=AI_NEWS_PROFILE,
        policy=_policy(),
        feature_builder=ai_news_feature_vector,
    )

    assert scored.metadata["memory_features_used"] is True
    assert "memory_structured_adjustment" in scored.metadata["memory_feature_names"]
    assert scored.ranking_features["memory_structured_adjustment"] > 0.0
    assert scored.score.value != baseline.score.value


class _SearchPort:
    def search(self, **kwargs):
        return [
            {
                "document_id": "doc-1",
                "score": 0.85,
                "text": "OpenAI launches agent memory",
                "metadata": {"topic": "agents", "confidence": 0.85},
            }
        ]


class _StructuredMemoryRepository:
    def list_decisions_for_target(self, target_type, target_id, *, limit=20):
        if target_type == "source":
            return [
                DecisionMemory(
                    decision_id="decision-1",
                    decision_type="source_reliability",
                    target_type=target_type,
                    target_id=target_id,
                    decision="pass",
                    run_id="run-1",
                )
            ]
        return []

    def list_events_by_topic(self, topic, *, limit=20):
        return [
            EventMemory(
                event_id="event-1",
                event_type="general_news",
                title="Agent memory adoption",
                summary="Agent memory adoption increased.",
                run_id="run-1",
                topic=topic,
                novelty_score=0.9,
            )
        ]

    def get_entity(self, entity_id):
        return EntityMemory(
            entity_id=entity_id,
            entity_type="organization",
            canonical_name="OpenAI",
            importance_score=0.8,
            trend_score=0.9,
        )

    def get_event(self, event_id):
        return None

    def find_similar_events(self, event, *, limit=2):
        return []

    def get_claim(self, claim_id):
        return None


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
