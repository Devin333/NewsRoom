from datetime import UTC, datetime

from backend.memory.intelligence_models import EventMemory
from backend.memory.timeline_service import TimelineService


def test_get_topic_timeline_returns_sorted_events() -> None:
    repository = _TimelineRepository()

    timeline = TimelineService(repository).get_topic_timeline("AI")

    assert [item.event_id for item in timeline.items] == ["event-new", "event-old"]
    assert "event-new" in timeline.latest_event().event_id
    assert "Recent" not in timeline.to_prompt_context()
    assert "New update" in timeline.to_prompt_context()


def test_get_entity_timeline_returns_entity_events() -> None:
    timeline = TimelineService(_TimelineRepository()).get_entity_timeline("entity-1")

    assert [item.event_id for item in timeline.items] == ["event-new"]


class _TimelineRepository:
    def list_events_by_topic(self, topic, *, limit=20):
        assert topic == "AI"
        return [
            EventMemory(
                event_id="event-old",
                event_type="general_news",
                title="Old update",
                summary="Old",
                run_id="run-1",
                topic="AI",
                event_time=datetime(2026, 5, 20, tzinfo=UTC),
            ),
            EventMemory(
                event_id="event-new",
                event_type="general_news",
                title="New update",
                summary="New",
                run_id="run-2",
                topic="AI",
                event_time=datetime(2026, 5, 21, tzinfo=UTC),
            ),
        ][:limit]

    def list_events_by_entity(self, entity_id, *, limit=20):
        assert entity_id == "entity-1"
        return [
            EventMemory(
                event_id="event-new",
                event_type="general_news",
                title="New update",
                summary="New",
                run_id="run-2",
                topic="AI",
                entity_ids=["entity-1"],
                event_time=datetime(2026, 5, 21, tzinfo=UTC),
            )
        ][:limit]
