from __future__ import annotations

from backend.foundation.models import BusinessFeedbackEvent, BusinessLearningSignal
from backend.foundation.primitives import build_stable_id


class LearningSignalBuilder:
    def build_from_feedback(self, events: list[BusinessFeedbackEvent]) -> list[BusinessLearningSignal]:
        if not events:
            return []
        board_type = events[0].board_type
        target_layer = events[0].target_layer
        feedback_type = events[0].feedback_type
        severity_score = min(1.0, sum(_severity_value(event.severity) for event in events) / max(1, len(events)))
        return [
            BusinessLearningSignal(
                signal_id=build_stable_id("learning", board_type or "", target_layer or "", feedback_type, [event.feedback_id for event in events]),
                signal_type=feedback_type,
                board_type=board_type,
                target_layer=target_layer,
                description=f"{feedback_type} occurred {len(events)} time(s).",
                frequency=len(events),
                severity_score=severity_score,
                related_feedback_ids=[event.feedback_id for event in events],
                suggested_policy_profile_id=events[0].related_policy_profile_id,
                suggested_adjustment={feedback_type: "review"},
            )
        ]


def _severity_value(severity: str) -> float:
    return {
        "info": 0.2,
        "warning": 0.5,
        "error": 0.8,
        "block": 1.0,
    }.get(severity, 0.5)
