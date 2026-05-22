from __future__ import annotations

from business.foundation.feedback import ImprovementApplier, ImprovementProposal


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
    assert context.skipped_overrides[0]["proposal_id"] == "proposed"
    assert context.measurement_plan["compare_metrics"]
