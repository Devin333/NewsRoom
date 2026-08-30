from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc

from backend.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class MemoryRankingFeatures:
    source_reliability: float = 0.5
    topic_momentum: float = 0.0
    entity_importance: float = 0.0
    event_novelty: float = 0.5
    duplicate_penalty: float = 0.0
    contradiction_penalty: float = 0.0
    previous_quality_penalty: float = 0.0

    def final_adjustment(self) -> float:
        return (
            0.10 * self.source_reliability
            + 0.10 * self.topic_momentum
            + 0.10 * self.entity_importance
            + 0.15 * self.event_novelty
            - 0.20 * self.duplicate_penalty
            - 0.30 * self.contradiction_penalty
            - 0.15 * self.previous_quality_penalty
        )


@dataclass(frozen=True)
class MemoryFeatureInput:
    topic: str | None = None
    source_id: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    event_id: str | None = None
    base_score: float = 0.0


class MemoryFeatureComputer:
    def __init__(self, repository: IntelligenceMemoryQueryRepository) -> None:
        self.repository = repository

    def compute(
        self,
        item: MemoryFeatureInput,
    ) -> MemoryRankingFeatures:
        return MemoryRankingFeatures(
            source_reliability=self.compute_source_reliability(item.source_id),
            topic_momentum=self.compute_topic_momentum(item.topic),
            entity_importance=self.compute_entity_importance(item.entity_ids),
            event_novelty=self.compute_event_novelty(item.event_id, item.topic),
            duplicate_penalty=self.compute_duplicate_penalty(item.event_id, item.topic),
            contradiction_penalty=self.compute_contradiction_penalty(item.claim_ids),
            previous_quality_penalty=self.compute_previous_quality_penalty("topic", item.topic or ""),
        )

    def compute_source_reliability(
        self,
        source_id: str | None,
    ) -> float:
        if not source_id:
            return 0.5
        decisions = self.repository.list_decisions_for_target("source", source_id, limit=20)
        if not decisions:
            return 0.5
        positives = sum(1 for decision in decisions if decision.is_positive())
        return _clamp(positives / len(decisions))

    def compute_topic_momentum(
        self,
        topic: str | None,
    ) -> float:
        if not topic:
            return 0.0
        events = self.repository.list_events_by_topic(topic, limit=20)
        if not events:
            return 0.0
        cutoff = datetime.now(UTC) - timedelta(days=7)
        recent = sum(1 for event in events if _event_time(event) >= cutoff)
        return _clamp(recent / 10.0)

    def compute_entity_importance(
        self,
        entity_ids: list[str],
    ) -> float:
        scores: list[float] = []
        for entity_id in entity_ids:
            entity = self.repository.get_entity(entity_id)
            if entity is not None:
                scores.append(max(entity.importance_score, min(1.0, entity.trend_score)))
        if not scores:
            return 0.0
        return _clamp(sum(scores) / len(scores))

    def compute_event_novelty(
        self,
        event_id: str | None,
        topic: str | None,
    ) -> float:
        if event_id:
            event = self.repository.get_event(event_id)
            if event is not None:
                return _clamp(event.novelty_score)
        events = self.repository.list_events_by_topic(topic, limit=5) if topic else []
        if not events:
            return 1.0
        return _clamp(sum(event.novelty_score for event in events) / len(events))

    def compute_duplicate_penalty(
        self,
        event_id: str | None,
        topic: str | None,
    ) -> float:
        if event_id:
            event = self.repository.get_event(event_id)
            if event is not None and self.repository.find_similar_events(event, limit=2):
                return 0.5
        if topic and len(self.repository.list_events_by_topic(topic, limit=3)) > 1:
            return 0.2
        return 0.0

    def compute_contradiction_penalty(
        self,
        claim_ids: list[str],
    ) -> float:
        if not claim_ids:
            return 0.0
        claims = [claim for claim_id in claim_ids if (claim := self.repository.get_claim(claim_id)) is not None]
        if not claims:
            return 0.0
        contradicted = sum(1 for claim in claims if claim.status == "contradicted" or claim.contradicted_by)
        return _clamp(contradicted / len(claims))

    def compute_previous_quality_penalty(
        self,
        target_type: str,
        target_id: str,
    ) -> float:
        if not target_id:
            return 0.0
        decisions = self.repository.list_decisions_for_target(target_type, target_id, limit=10)
        if not decisions:
            return 0.0
        negative = sum(1 for decision in decisions if not decision.is_positive())
        return _clamp(negative / len(decisions))


def _event_time(event) -> datetime:
    value = event.event_time or event.detected_at
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = ["MemoryFeatureComputer", "MemoryFeatureInput", "MemoryRankingFeatures"]
