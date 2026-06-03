from __future__ import annotations

from business.foundation.feedback import ImprovementProposalBuilder, ImprovementRecommendation
from business.foundation.feedback.proposal_builder import risk_level_for_severity


def test_proposal_builder_converts_recommendation_to_policy_experiment_profile() -> None:
    recommendation = ImprovementRecommendation(
        recommendation_id="rec-1",
        source="learning_signal",
        board_type="ai_news",
        target_type="ranking_weight_override",
        target_id="top_cards",
        severity="error",
        reason="Top cards miss evidence.",
        suggested_action="raise evidence coverage requirement",
        evidence=[{"feedback_id": "fb-1"}],
    )

    proposal = ImprovementProposalBuilder().build_from_recommendations([recommendation])[0]

    assert proposal.change_type == "policy_experiment"
    assert proposal.target_type == "ranking_weight"
    assert proposal.risk_level == "high"
    assert proposal.experiment_profile is not None
    assert proposal.experiment_profile.target_type == "ranking_weight"
    assert proposal.experiment_profile.parameters == {
        "severity": "error",
        "evidence_count": 1,
    }
    assert proposal.policy_experiment_parameters == {
        "severity": "error",
        "evidence_count": 1,
    }
    assert proposal.to_dict()["policy_experiment_parameters"] == proposal.policy_experiment_parameters
    assert "proposed_patch" not in proposal.to_dict()


def test_risk_level_for_severity_maps_review_priority() -> None:
    assert risk_level_for_severity("block") == "critical"
    assert risk_level_for_severity("error") == "high"
    assert risk_level_for_severity("warning") == "medium"
    assert risk_level_for_severity("info") == "low"
