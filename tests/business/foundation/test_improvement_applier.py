from __future__ import annotations

from business.foundation.feedback import (
    ImprovementApplier,
    ImprovementProposal,
    LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES,
    SUPPORTED_OVERRIDE_TYPES,
    PolicyExperimentProfile,
    is_legacy_policy_experiment_change_type,
)


def test_improvement_applier_only_applies_approved_supported_proposals() -> None:
    proposals = [
        ImprovementProposal(
            proposal_id="approved",
            recommendation_id="rec-1",
            board_type="ai_news",
            change_type="ranking_weight_override",
            target_type="ranking_weight_override",
            target_id="freshness",
            proposed_patch={"weight": 1.1},
            risk_level="medium",
            requires_approval=True,
            status="approved",
        ),
        ImprovementProposal(
            proposal_id="proposed",
            recommendation_id="rec-2",
            board_type="ai_news",
            change_type="ranking_weight_override",
            target_type="ranking_weight_override",
            target_id="novelty",
            proposed_patch={"weight": 1.1},
            risk_level="medium",
            requires_approval=True,
            status="proposed",
        ),
    ]

    context = ImprovementApplier().apply(proposals, run_id="run-1", board_type="ai_news")

    assert [item["proposal_id"] for item in context.applied_overrides] == ["approved"]
    assert context.applied_overrides[0]["target_type"] == "ranking_weight"
    assert context.applied_policy_experiments == context.applied_overrides
    assert context.skipped_policy_experiments == context.skipped_overrides
    assert context.skipped_overrides[0]["proposal_id"] == "proposed"
    assert context.measurement_plan["compare_metrics"]


def test_improvement_applier_applies_policy_experiment_profiles() -> None:
    proposal = ImprovementProposal(
        proposal_id="experiment",
        recommendation_id="rec-3",
        board_type="ai_news",
        change_type="policy_experiment",
        target_type="ranking_weight",
        target_id="freshness",
        proposed_patch={},
        risk_level="medium",
        requires_approval=True,
        status="approved",
        experiment_profile=PolicyExperimentProfile(
            profile_id="policy-exp-1",
            board_type="ai_news",
            target_type="ranking_weight",
            target_id="freshness",
            parameters={"severity": "warning"},
            rationale="Freshness underperformed.",
            suggested_action="rebalance ranking freshness",
        ),
    )

    context = ImprovementApplier().apply([proposal], run_id="run-2", board_type="ai_news")

    applied = context.applied_overrides[0]
    assert applied["profile_id"] == "policy-exp-1"
    assert applied["parameters"] == {"severity": "warning"}
    assert "patch" not in applied
    assert context.applied_policy_experiments == context.applied_overrides


def test_legacy_override_type_name_is_compatibility_alias() -> None:
    assert SUPPORTED_OVERRIDE_TYPES is LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES
    assert is_legacy_policy_experiment_change_type("ranking_weight_override") is True
    assert is_legacy_policy_experiment_change_type("policy_experiment") is False
