from __future__ import annotations

from business.foundation.feedback import ImprovementProposal, SelfImprovementReportBuilder


def test_self_improvement_report_builder_summarizes_high_risk_proposals() -> None:
    proposal = ImprovementProposal(
        proposal_id="proposal-1",
        recommendation_id="rec-1",
        board_type="ai_news",
        change_type="policy_experiment",
        target_type="policy_threshold",
        target_id="threshold",
        proposed_patch={},
        risk_level="high",
        requires_approval=True,
        status="proposed",
    )

    report = SelfImprovementReportBuilder().build(
        feedback_events=[{"feedback_id": "feedback-1"}],
        learning_signals=[{"signal_id": "signal-1"}],
        recommendations=[{"recommendation_id": "rec-1"}],
        proposals=[proposal],
        applied_overrides=[{"proposal_id": "proposal-1"}],
        measurement={"quality_score_delta": 0.2},
    )

    assert report.risks == ["proposal-1:high"]
    assert report.next_actions == ["review proposed improvements"]
    assert report.proposals[0]["proposal_id"] == "proposal-1"
    assert report.measurement == {"quality_score_delta": 0.2}


def test_self_improvement_report_builder_uses_monitoring_action_without_proposals() -> None:
    report = SelfImprovementReportBuilder().build(
        feedback_events=[],
        learning_signals=[],
        recommendations=[],
        proposals=[],
        applied_overrides=[],
        measurement=None,
    )

    assert report.risks == []
    assert report.next_actions == ["continue monitoring"]
    assert report.measurement == {}
