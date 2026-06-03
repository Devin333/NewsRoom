from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.ai_news.runner import AINewsRunner
from business.foundation.feedback import ImprovementProposal
from business.evaluation.fixtures import sample_signal


def test_approved_proposal_is_applied_on_next_board_run(tmp_path) -> None:
    improvement_service = BoardImprovementService()
    proposal = improvement_service.proposal_store.save(
        ImprovementProposal(
            proposal_id="approved-ranking",
            recommendation_id="rec-1",
            board_type="ai_news",
            change_type="ranking_weight_override",
            target_type="ranking_weight_override",
            target_id="freshness",
            policy_experiment_parameters={"weight": 1.2},
            risk_level="medium",
            requires_approval=True,
            status="proposed",
        )
    )
    improvement_service.proposal_store.approve(proposal.proposal_id)

    result = AINewsRunner(
        artifact_root=tmp_path,
        improvement_service=improvement_service,
    ).run(signals=[sample_signal("ai_news")], topic="Agent Memory", run_id="approved-next-run")

    policy_context = result.output["policy_experiment_application_context"]
    applied = result.output["applied_policy_experiments"]
    assert applied and applied[0]["proposal_id"] == "approved-ranking"
    assert policy_context["applied_policy_experiments"] == applied
    assert "applied_overrides" not in result.output
    assert result.output["improvement_measurement"]
