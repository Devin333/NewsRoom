from __future__ import annotations

import pytest

from business.foundation import (
    BusinessFeedbackEvent,
    BusinessQualityCheck,
    PolicyLoader,
    RegressionGuardRunner,
    activate_policy_candidate,
    build_feedback_events_from_quality,
    build_runtime_quality_closure,
    quality_snapshot_from_checks,
)
from business.foundation.feedback import FeedbackAggregator


def test_quality_failure_flows_to_feedback_learning_candidate_and_guard() -> None:
    check = BusinessQualityCheck.create(
        "board_card_missing_evidence",
        passed=False,
        severity="error",
        reason="Board card must include evidence.",
    )
    quality = quality_snapshot_from_checks([check], score=0.4, confidence=0.8)
    profile = PolicyLoader().require_active_profile("ai_news_ranking")
    feedback = build_feedback_events_from_quality(
        quality,
        target_object_type="board_card",
        target_object_id="card-1",
        target_layer="output",
        board_type="ai_news",
        policy_profile=profile,
    )
    closure = build_runtime_quality_closure(feedback, base_policy_profile=profile)

    assert feedback
    assert closure.learning_signals
    assert closure.policy_candidates
    assert closure.guard_results
    assert closure.policy_candidates[0].profile.status == "candidate"
    with pytest.raises(ValueError):
        activate_policy_candidate(closure.policy_candidates[0], closure.guard_results[0], manual_approval=False)


def test_repeated_feedback_groups_by_board_layer_type_and_severity() -> None:
    events = [
        BusinessFeedbackEvent.create(
            target_object_type="cross_board_path",
            board_type="cross_board",
            target_layer="cross_board_graph",
            feedback_type="duplicate_evidence",
            severity="warning",
            target_object_id=f"path-{index}",
        )
        for index in range(2)
    ]
    grouped = FeedbackAggregator().group_by_type(events)
    closure = build_runtime_quality_closure(events, base_policy_profile=PolicyLoader().require_active_profile("cross_board_ranking"))

    assert list(grouped) == [("cross_board", "cross_board_graph", "duplicate_evidence", "warning")]
    assert closure.learning_signals[0].frequency == 2
