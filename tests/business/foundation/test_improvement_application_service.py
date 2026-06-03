from __future__ import annotations

from business.foundation.feedback import (
    ImprovementApplicationService,
    ImprovementProposal,
    InMemoryImprovementProposalStore,
    PolicyExperimentProfile,
)


def test_improvement_application_service_filters_store_proposals_by_board() -> None:
    store = InMemoryImprovementProposalStore()
    ai_proposal = store.save(_proposal("proposal-ai", board_type="ai_news")).with_status("approved")
    paper_proposal = store.save(_proposal("proposal-paper", board_type="paper_radar")).with_status("approved")
    store.save(ai_proposal)
    store.save(paper_proposal)

    context = ImprovementApplicationService(proposal_store=store).apply_approved_policy_experiments(
        run_id="run-1",
        board_type="ai_news",
    )

    assert context.proposal_ids == ["proposal-ai"]
    assert [item["proposal_id"] for item in context.applied_policy_experiments] == ["proposal-ai"]
    assert context.skipped_policy_experiments == []
    assert context.skipped_overrides == []

    legacy_context = ImprovementApplicationService(proposal_store=store).apply_approved(
        run_id="run-2",
        board_type="ai_news",
    )
    assert legacy_context.applied_overrides == legacy_context.applied_policy_experiments
    assert legacy_context.skipped_overrides == legacy_context.skipped_policy_experiments


def _proposal(proposal_id: str, *, board_type: str) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=proposal_id,
        recommendation_id=f"rec-{proposal_id}",
        board_type=board_type,
        change_type="policy_experiment",
        target_type="policy_threshold",
        target_id="threshold",
        policy_experiment_parameters={},
        risk_level="medium",
        requires_approval=True,
        status="proposed",
        experiment_profile=PolicyExperimentProfile(
            profile_id=f"profile-{proposal_id}",
            board_type=board_type,
            target_type="policy_threshold",
            target_id="threshold",
            parameters={"severity": "warning"},
            rationale="test",
            suggested_action="review threshold",
        ),
    )
