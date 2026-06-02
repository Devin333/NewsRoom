from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.foundation import BusinessFeedbackEvent, BusinessQualityCheck, quality_snapshot_from_checks


def test_feedback_full_loop_reaches_approved_override_and_measurement() -> None:
    quality = quality_snapshot_from_checks(
        [
            BusinessQualityCheck.create(
                "top_cards_have_evidence",
                passed=False,
                severity="error",
                reason="Top card is missing evidence.",
            )
        ],
        score=0.35,
    )
    event = BusinessFeedbackEvent.create(
        target_object_type="board_run",
        target_object_id="run-1",
        target_layer="board",
        board_type="ai_news",
        feedback_type="top_cards_have_evidence",
        severity="error",
    )
    service = BoardImprovementService()

    feedback = service.collect_feedback([event])
    learning = service.build_learning_signals(feedback)
    recommendations = service.build_recommendations(learning, board_type="ai_news", quality_summary=quality)
    proposals = service.build_proposals(recommendations)

    assert feedback and learning and recommendations and proposals
    assert proposals[0].change_type == "policy_experiment"
    assert proposals[0].experiment_profile is not None
    assert proposals[0].proposed_patch == {}
    assert service.apply_approved_overrides(run_id="before", board_type="ai_news").applied_overrides == []

    service.proposal_store.approve(proposals[0].proposal_id)
    context = service.apply_approved_overrides(run_id="after", board_type="ai_news")
    measurement = service.measure(
        {"quality_score": 0.35, "card_count": 0, "evidence_coverage": 0.0, "duplicate_rate": 0.5, "empty_output": True, "subscription_match": 0.0},
        {"quality_score": 0.7, "card_count": 2, "evidence_coverage": 1.0, "duplicate_rate": 0.0, "empty_output": False, "subscription_match": 1.0},
    )
    report = service.build_report(
        feedback_events=feedback,
        learning_signals=learning,
        recommendations=recommendations,
        proposals=proposals,
        applied_overrides=context.applied_overrides,
        measurement=measurement,
    )

    assert context.applied_overrides
    assert context.applied_overrides[0]["profile_id"] == proposals[0].experiment_profile.profile_id
    assert measurement.quality_score_delta == 0.35
    assert report.applied_overrides
