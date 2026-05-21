from __future__ import annotations

from business.foundation.models import BoardRunResult, BusinessFeedbackEvent


class FeedbackCollector:
    def collect(self, results: list[BoardRunResult]) -> list[BusinessFeedbackEvent]:
        events: list[BusinessFeedbackEvent] = []
        for result in results:
            events.extend(result.feedback_candidates)
        return events
