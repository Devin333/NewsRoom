from __future__ import annotations

import pytest

from backend.foundation import (
    BoardType,
    BusinessFeedbackEvent,
    BusinessLearningSignal,
    BusinessPolicyProfile,
    BusinessQualityCheck,
    PolicyLoader,
    RegressionGuardRunner,
    activate_policy_candidate,
    build_policy_candidate,
    create_policy_snapshot,
    quality_snapshot_from_checks,
)
from backend.foundation.feedback import FeedbackAggregator, LearningSignalBuilder


def test_quality_feedback_policy_loop_models_are_traceable() -> None:
    check = BusinessQualityCheck.create(
        "top_cards_have_evidence",
        passed=False,
        severity="error",
        reason="Top card has no evidence.",
    )
    snapshot = quality_snapshot_from_checks([check], score=0.4, confidence=0.7)
    event = BusinessFeedbackEvent.create(
        target_object_type="board_card",
        target_object_id="card-1",
        board_type=BoardType.AI_NEWS.value,
        feedback_type=check.check_type,
        severity=check.severity,
        observed=check.observed,
    )

    assert snapshot.status == "failed"
    assert event.feedback_id.startswith("fb_")
    assert event.board_type == "ai_news"


def test_learning_signal_and_policy_candidate_require_guard_and_manual_activation() -> None:
    event = BusinessFeedbackEvent.create(
        target_object_type="board_run",
        board_type="project_radar",
        feedback_type="star_spike_overweighted",
        severity="error",
    )
    grouped = FeedbackAggregator().group_by_type([event])
    signal = LearningSignalBuilder().build_from_feedback(next(iter(grouped.values())))[0]
    profile = PolicyLoader().require_active_profile("project_radar_ranking")
    candidate = build_policy_candidate(signal, profile)
    guard = RegressionGuardRunner().run(candidate)

    assert isinstance(signal, BusinessLearningSignal)
    assert candidate.profile.status == "candidate"
    assert guard.passed
    with pytest.raises(ValueError):
        activate_policy_candidate(candidate, guard, manual_approval=False)
    assert activate_policy_candidate(candidate, guard, manual_approval=True).status == "active"


def test_policy_snapshot_binds_run_id() -> None:
    profiles = PolicyLoader().active_profiles(board_type=BoardType.AI_NEWS)
    snapshot = create_policy_snapshot("run-1", profiles)

    assert snapshot.run_id == "run-1"
    assert snapshot.profiles
    assert all(isinstance(profile, BusinessPolicyProfile) for profile in snapshot.profiles)
