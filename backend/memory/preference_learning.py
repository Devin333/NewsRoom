from __future__ import annotations

from typing import Any

from backend.memory.feedback_memory import FeedbackMemory, FeedbackMemoryService
from backend.memory.intelligence_models import PreferenceMemory


class PreferenceLearningService:
    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.feedback_service = FeedbackMemoryService(repository)

    def learn_from_feedback(self, feedback_items: list[FeedbackMemory]) -> list[PreferenceMemory]:
        preferences: list[PreferenceMemory] = []
        for feedback in feedback_items:
            if feedback.feedback_type in {"topic_subscribe", "topic_mute"}:
                preferences.extend(self.update_topic_preference(feedback))
            elif feedback.feedback_type in {"source_block", "source_boost"}:
                preferences.extend(self.update_source_preference(feedback))
            elif feedback.feedback_type == "ranking_override":
                preferences.extend(self.update_ranking_preference(feedback))
        if preferences:
            self.repository.save_preferences(preferences)
        return preferences

    def update_topic_preference(self, feedback: FeedbackMemory) -> list[PreferenceMemory]:
        return self.feedback_service.feedback_to_preference(feedback)

    def update_source_preference(self, feedback: FeedbackMemory) -> list[PreferenceMemory]:
        return self.feedback_service.feedback_to_preference(feedback)

    def update_ranking_preference(self, feedback: FeedbackMemory) -> list[PreferenceMemory]:
        return self.feedback_service.feedback_to_preference(feedback)


__all__ = ["PreferenceLearningService"]
