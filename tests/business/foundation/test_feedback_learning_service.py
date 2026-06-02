from __future__ import annotations

from business.foundation import BoardType, BusinessFeedbackEvent
from business.foundation.feedback import FeedbackLearningService, dedupe_feedback_events


def test_feedback_learning_service_dedupes_events_and_builds_grouped_signals() -> None:
    event = _event("event-1")
    duplicate = event
    related = _event("event-2")

    result = FeedbackLearningService().build([event, duplicate, related])

    assert result.feedback_events == [event, related]
    assert len(result.learning_signals) == 1
    assert result.learning_signals[0].frequency == 2
    assert result.learning_signals[0].related_feedback_ids == [event.feedback_id, related.feedback_id]


def test_dedupe_feedback_events_preserves_first_seen_order() -> None:
    first = _event("event-1")
    second = _event("event-2")

    assert dedupe_feedback_events([first, second, first]) == [first, second]


def _event(target_id: str) -> BusinessFeedbackEvent:
    return BusinessFeedbackEvent.create(
        target_object_type="board_run",
        target_object_id=target_id,
        target_layer="board",
        board_type=BoardType.AI_NEWS.value,
        feedback_type="top_cards_have_evidence",
        severity="error",
    )
