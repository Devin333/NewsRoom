from __future__ import annotations

from business.foundation.feedback import (
    ImprovementProposal,
    PolicyExperimentApplicationContext,
    PolicyExperimentProfile,
    SelfImprovementReportBuilder,
)


def test_self_improvement_report_builder_summarizes_high_risk_proposals() -> None:
    proposal = ImprovementProposal(
        proposal_id="proposal-1",
        recommendation_id="rec-1",
        board_type="ai_news",
        change_type="policy_experiment",
        target_type="policy_threshold",
        target_id="threshold",
        policy_experiment_parameters={"severity": "error"},
        risk_level="high",
        requires_approval=True,
        status="proposed",
        experiment_profile=PolicyExperimentProfile(
            profile_id="profile-1",
            board_type="ai_news",
            target_type="policy_threshold",
            target_id="threshold",
            parameters={"severity": "error"},
            rationale="Quality threshold needs review.",
            suggested_action="run a policy threshold experiment",
        ),
    )

    report = SelfImprovementReportBuilder().build(
        feedback_events=[{"feedback_id": "feedback-1"}],
        learning_signals=[{"signal_id": "signal-1"}],
        recommendations=[{"recommendation_id": "rec-1"}],
        proposals=[proposal],
        applied_policy_experiments=[{"proposal_id": "proposal-1"}],
        measurement={"quality_score_delta": 0.2},
    )

    assert report.risks == ["proposal-1:high"]
    assert report.next_actions == ["review proposed improvements"]
    assert report.proposals[0]["proposal_id"] == "proposal-1"
    assert report.policy_experiment_profiles == [
        {
            "profile_id": "profile-1",
            "board_type": "ai_news",
            "target_type": "policy_threshold",
            "target_id": "threshold",
            "parameters": {"severity": "error"},
            "rationale": "Quality threshold needs review.",
            "suggested_action": "run a policy threshold experiment",
            "measurement_metrics": [
                "quality_score",
                "card_count",
                "evidence_coverage",
                "duplicate_rate",
                "empty_output",
                "subscription_match",
            ],
            "created_at": report.policy_experiment_profiles[0]["created_at"],
        }
    ]
    assert report.policy_experiment_profile_ids == ["profile-1"]
    assert report.applied_policy_experiments == [{"proposal_id": "proposal-1"}]
    assert report.applied_overrides == report.applied_policy_experiments
    assert report.measurement == {"quality_score_delta": 0.2}


def test_self_improvement_report_builder_uses_monitoring_action_without_proposals() -> None:
    report = SelfImprovementReportBuilder().build(
        feedback_events=[],
        learning_signals=[],
        recommendations=[],
        proposals=[],
        measurement=None,
    )

    assert report.risks == []
    assert report.next_actions == ["continue monitoring"]
    assert report.measurement == {}


def test_self_improvement_report_builder_prefers_policy_experiment_field() -> None:
    report = SelfImprovementReportBuilder().build(
        feedback_events=[],
        learning_signals=[],
        recommendations=[],
        proposals=[],
        applied_policy_experiments=[{"proposal_id": "proposal-1", "profile_id": "profile-1"}],
        measurement={},
    )

    assert report.applied_policy_experiments == [{"proposal_id": "proposal-1", "profile_id": "profile-1"}]
    assert report.applied_overrides == report.applied_policy_experiments


def test_self_improvement_report_builder_uses_policy_experiment_application_context() -> None:
    context = PolicyExperimentApplicationContext(
        run_id="run-1",
        board_type="ai_news",
        applied_policy_experiments=[{"proposal_id": "proposal-1", "profile_id": "profile-1"}],
        skipped_policy_experiments=[{"proposal_id": "proposal-2", "reason": "not_approved"}],
    )

    report = SelfImprovementReportBuilder().build(
        feedback_events=[],
        learning_signals=[],
        recommendations=[],
        proposals=[],
        policy_experiment_application_context=context,
        measurement={},
    )

    assert report.applied_policy_experiments == context.applied_policy_experiments
    assert report.applied_overrides == report.applied_policy_experiments
