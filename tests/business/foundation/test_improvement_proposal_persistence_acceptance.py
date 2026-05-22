from __future__ import annotations

from business.foundation.feedback import ImprovementProposal, LocalJsonImprovementProposalStore


def test_local_json_improvement_proposal_store_acceptance(tmp_path) -> None:
    path = tmp_path / "proposal-state.json"
    store = LocalJsonImprovementProposalStore(path)
    store.save(_proposal("proposal-save"))
    store.save(_proposal("proposal-approve"))
    store.save(_proposal("proposal-reject"))
    store.save(_proposal("proposal-apply"))

    reloaded = LocalJsonImprovementProposalStore(path)
    assert reloaded.get("proposal-save").status == "proposed"

    reloaded.approve("proposal-approve")
    assert LocalJsonImprovementProposalStore(path).get("proposal-approve").status == "approved"
    assert [proposal.proposal_id for proposal in LocalJsonImprovementProposalStore(path).list(status="approved")] == [
        "proposal-approve"
    ]

    LocalJsonImprovementProposalStore(path).reject("proposal-reject")
    assert LocalJsonImprovementProposalStore(path).get("proposal-reject").status == "rejected"

    applied_store = LocalJsonImprovementProposalStore(path)
    applied_store.approve("proposal-apply")
    applied_store.mark_applied("proposal-apply")
    assert LocalJsonImprovementProposalStore(path).get("proposal-apply").status == "applied"


def _proposal(proposal_id: str) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=proposal_id,
        recommendation_id=f"rec-{proposal_id}",
        board_type="ai_news",
        change_type="ranking_weight_override",
        target_type="ranking_weight_override",
        target_id="freshness",
        proposed_patch={"weight": 1.1},
        risk_level="medium",
        requires_approval=True,
        status="proposed",
    )
