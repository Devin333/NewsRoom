from datetime import UTC, datetime

from business.memory.intelligence_models import ClaimMemory, DecisionMemory, EntityMemory, EventMemory
from business.memory.memory_features import MemoryFeatureComputer, MemoryFeatureInput, MemoryRankingFeatures


def test_memory_ranking_features_final_adjustment_uses_penalties() -> None:
    features = MemoryRankingFeatures(
        source_reliability=1.0,
        topic_momentum=1.0,
        entity_importance=1.0,
        event_novelty=1.0,
        duplicate_penalty=1.0,
        contradiction_penalty=1.0,
        previous_quality_penalty=1.0,
    )

    assert features.final_adjustment() < 0


def test_memory_feature_computer_returns_bounded_features() -> None:
    features = MemoryFeatureComputer(_FeatureRepository()).compute(
        MemoryFeatureInput(
            topic="AI",
            source_id="source-1",
            entity_ids=["entity-1"],
            claim_ids=["claim-1"],
            event_id="event-1",
        )
    )

    assert features.source_reliability == 0.5
    assert 0.0 <= features.topic_momentum <= 1.0
    assert features.entity_importance == 0.8
    assert features.event_novelty == 0.7
    assert features.duplicate_penalty == 0.5
    assert features.contradiction_penalty == 1.0


class _FeatureRepository:
    def list_decisions_for_target(self, target_type, target_id, *, limit=20):
        return [
            DecisionMemory(
                decision_id="decision-1",
                decision_type="quality_gate",
                target_type=target_type,
                target_id=target_id,
                decision="pass",
                run_id="run-1",
            ),
            DecisionMemory(
                decision_id="decision-2",
                decision_type="quality_gate",
                target_type=target_type,
                target_id=target_id,
                decision="fail",
                run_id="run-2",
            ),
        ][:limit]

    def list_events_by_topic(self, topic, *, limit=20):
        return [
            EventMemory(
                event_id="event-1",
                event_type="general_news",
                title="Update",
                summary="Summary",
                run_id="run-1",
                topic=topic,
                novelty_score=0.7,
                event_time=datetime.now(UTC),
            ),
            EventMemory(
                event_id="event-2",
                event_type="general_news",
                title="Update 2",
                summary="Summary",
                run_id="run-2",
                topic=topic,
                novelty_score=0.3,
                event_time=datetime(2020, 1, 1, tzinfo=UTC),
            ),
        ][:limit]

    def get_entity(self, entity_id):
        return EntityMemory(
            entity_id=entity_id,
            entity_type="organization",
            canonical_name="OpenAI",
            importance_score=0.8,
            trend_score=0.2,
        )

    def get_event(self, event_id):
        return EventMemory(
            event_id=event_id,
            event_type="general_news",
            title="Update",
            summary="Summary",
            run_id="run-1",
            novelty_score=0.7,
        )

    def find_similar_events(self, event, *, limit=2):
        return [event]

    def get_claim(self, claim_id):
        return ClaimMemory(
            claim_id=claim_id,
            run_id="run-1",
            text="Claim",
            status="contradicted",
            contradicted_by=["ev-1"],
        )
