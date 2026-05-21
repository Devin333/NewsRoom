from __future__ import annotations

from collections import defaultdict

from business.foundation.models import BusinessFeedbackEvent


class FeedbackAggregator:
    def group_by_type(self, events: list[BusinessFeedbackEvent]) -> dict[tuple[str | None, str | None, str, str], list[BusinessFeedbackEvent]]:
        grouped: dict[tuple[str | None, str | None, str, str], list[BusinessFeedbackEvent]] = defaultdict(list)
        for event in events:
            grouped[(event.board_type, event.target_layer, event.feedback_type, event.severity)].append(event)
        return dict(grouped)
