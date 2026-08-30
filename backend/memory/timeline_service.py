from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from backend.memory.intelligence_models import EventMemory, utc_now
from backend.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class TimelineItem:
    event_id: str
    title: str
    summary: str
    event_type: str
    event_time: datetime | None
    detected_at: datetime
    topic: str | None
    entity_ids: list[str]
    claim_ids: list[str]
    evidence_ids: list[str]
    impact_score: float
    novelty_score: float

    def to_prompt_line(self) -> str:
        timestamp = self.event_time or self.detected_at
        date_text = timestamp.date().isoformat()
        return f"{date_text} [{self.event_type}] {self.title}: {self.summary}".strip()


@dataclass(frozen=True)
class Timeline:
    target_type: Literal["entity", "topic"]
    target_id: str
    items: list[TimelineItem]
    generated_at: datetime = field(default_factory=utc_now)

    def is_empty(self) -> bool:
        return not self.items

    def to_prompt_context(self, *, limit: int = 10) -> str:
        if not self.items:
            return ""
        return "\n".join(f"- {item.to_prompt_line()}" for item in self.items[:limit])

    def latest_event(self) -> TimelineItem | None:
        return self.items[0] if self.items else None


class TimelineService:
    def __init__(self, repository: IntelligenceMemoryQueryRepository) -> None:
        self.repository = repository

    def get_entity_timeline(
        self,
        entity_id: str,
        *,
        limit: int = 20,
    ) -> Timeline:
        events = self.repository.list_events_by_entity(entity_id, limit=limit)
        return Timeline(
            target_type="entity",
            target_id=entity_id,
            items=[self._event_to_timeline_item(event) for event in _sort_events(events)],
        )

    def get_topic_timeline(
        self,
        topic: str,
        *,
        limit: int = 20,
    ) -> Timeline:
        events = self.repository.list_events_by_topic(topic, limit=limit)
        return Timeline(
            target_type="topic",
            target_id=topic,
            items=[self._event_to_timeline_item(event) for event in _sort_events(events)],
        )

    def summarize_timeline(
        self,
        timeline: Timeline,
        *,
        limit: int = 10,
    ) -> str:
        return timeline.to_prompt_context(limit=limit)

    def _event_to_timeline_item(
        self,
        event: EventMemory,
    ) -> TimelineItem:
        return TimelineItem(
            event_id=event.event_id,
            title=event.title,
            summary=event.summary,
            event_type=event.event_type,
            event_time=event.event_time,
            detected_at=event.detected_at,
            topic=event.topic,
            entity_ids=list(event.entity_ids),
            claim_ids=list(event.claim_ids),
            evidence_ids=list(event.evidence_ids),
            impact_score=event.impact_score,
            novelty_score=event.novelty_score,
        )


def _sort_events(events: list[EventMemory]) -> list[EventMemory]:
    return sorted(events, key=lambda event: event.event_time or event.detected_at, reverse=True)


__all__ = ["Timeline", "TimelineItem", "TimelineService"]
