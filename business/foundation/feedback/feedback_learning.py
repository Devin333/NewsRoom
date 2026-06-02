from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from business.foundation.models import BusinessFeedbackEvent, BusinessLearningSignal
from business.foundation.feedback.feedback_aggregator import FeedbackAggregator
from business.foundation.feedback.learning_signal_builder import LearningSignalBuilder


@dataclass(frozen=True)
class FeedbackLearningResult:
    feedback_events: list[BusinessFeedbackEvent]
    learning_signals: list[BusinessLearningSignal]

    def to_dict(self) -> dict[str, object]:
        return {
            "feedback_events": [event.to_dict() for event in self.feedback_events],
            "learning_signals": [signal.to_dict() for signal in self.learning_signals],
        }


class FeedbackLearningService:
    def __init__(
        self,
        *,
        aggregator: FeedbackAggregator | None = None,
        learning_signal_builder: LearningSignalBuilder | None = None,
    ) -> None:
        self.aggregator = aggregator or FeedbackAggregator()
        self.learning_signal_builder = learning_signal_builder or LearningSignalBuilder()

    def collect(self, feedback_events: Iterable[BusinessFeedbackEvent]) -> list[BusinessFeedbackEvent]:
        return dedupe_feedback_events(feedback_events)

    def build_learning_signals(
        self,
        feedback_events: Iterable[BusinessFeedbackEvent],
    ) -> list[BusinessLearningSignal]:
        signals: list[BusinessLearningSignal] = []
        grouped = self.aggregator.group_by_type(list(feedback_events))
        for events in grouped.values():
            signals.extend(self.learning_signal_builder.build_from_feedback(events))
        return signals

    def build(self, feedback_events: Iterable[BusinessFeedbackEvent]) -> FeedbackLearningResult:
        collected = self.collect(feedback_events)
        return FeedbackLearningResult(
            feedback_events=collected,
            learning_signals=self.build_learning_signals(collected),
        )


def dedupe_feedback_events(feedback_events: Iterable[BusinessFeedbackEvent]) -> list[BusinessFeedbackEvent]:
    seen: set[str] = set()
    result: list[BusinessFeedbackEvent] = []
    for event in feedback_events:
        if event.feedback_id in seen:
            continue
        seen.add(event.feedback_id)
        result.append(event)
    return result


__all__ = ["FeedbackLearningResult", "FeedbackLearningService", "dedupe_feedback_events"]
