from __future__ import annotations

from typing import Any

from business.foundation import BusinessFeedbackEvent, build_feedback_events_from_quality


class BoardFeedbackService:
    def collect(
        self,
        *,
        board_run_result: Any,
        quality_summary: Any,
        existing_events: list[BusinessFeedbackEvent] | None = None,
    ) -> list[BusinessFeedbackEvent]:
        policy_profile = None
        policy_snapshot = getattr(board_run_result, "policy_snapshot", None)
        if policy_snapshot is not None and getattr(policy_snapshot, "profiles", None):
            policy_profile = policy_snapshot.profiles[0]
        return build_feedback_events_from_quality(
            quality_summary,
            target_object_type="board_run",
            target_object_id=str(getattr(board_run_result, "run_id", "")),
            target_layer="board",
            board_type=str(getattr(getattr(board_run_result, "board_type", None), "value", getattr(board_run_result, "board_type", ""))),
            policy_profile=policy_profile,
            existing_events=existing_events or getattr(board_run_result, "feedback_candidates", []) or [],
        )


__all__ = ["BoardFeedbackService"]
