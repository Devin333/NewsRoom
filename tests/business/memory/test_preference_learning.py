from business.memory.feedback_memory import FeedbackMemory
from business.memory.preference_learning import PreferenceLearningService


def test_preference_learning_persists_topic_source_and_ranking_preferences() -> None:
    repository = _PreferenceRepository()
    service = PreferenceLearningService(repository)

    preferences = service.learn_from_feedback(
        [
            FeedbackMemory(
                feedback_id="fb-topic",
                feedback_type="topic_subscribe",
                target_type="topic",
                target_id="AI",
                content="Follow closely",
            ),
            FeedbackMemory(
                feedback_id="fb-source",
                feedback_type="source_boost",
                target_type="source",
                target_id="source-1",
                weight=0.8,
            ),
            FeedbackMemory(
                feedback_id="fb-ranking",
                feedback_type="ranking_override",
                target_type="ranking",
                target_id="daily",
                content="Prefer evidence-backed claims",
            ),
        ]
    )

    assert len(preferences) == 3
    assert [preference.owner_type for preference in preferences] == ["topic", "source", "ranking"]
    assert repository.saved == preferences


def test_preference_learning_ignores_non_preference_feedback() -> None:
    repository = _PreferenceRepository()
    service = PreferenceLearningService(repository)

    preferences = service.learn_from_feedback(
        [
            FeedbackMemory(
                feedback_id="fb-like",
                feedback_type="like",
                target_type="report",
                target_id="report-1",
            )
        ]
    )

    assert preferences == []
    assert repository.saved == []


class _PreferenceRepository:
    def __init__(self) -> None:
        self.saved = []

    def save_preferences(self, preferences):
        self.saved.extend(preferences)
