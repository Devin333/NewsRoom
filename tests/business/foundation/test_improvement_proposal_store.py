from __future__ import annotations

from business.foundation.feedback import ImprovementProposal, InMemoryImprovementProposalStore, LocalJsonImprovementProposalStore


def _proposal() -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id="proposal-1",
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


def test_in_memory_proposal_store_approval_flow() -> None:
    store = InMemoryImprovementProposalStore()
    store.save(_proposal())

    assert store.get("proposal-1").status == "proposed"
    assert store.approve("proposal-1").status == "approved"
    assert store.mark_applied("proposal-1").status == "applied"
    assert store.list(status="applied")[0].proposal_id == "proposal-1"


def test_local_json_proposal_store_round_trips(tmp_path) -> None:
    store = LocalJsonImprovementProposalStore(tmp_path)
    store.save(_proposal())
    store.approve("proposal-1")

    loaded = LocalJsonImprovementProposalStore(tmp_path)
    assert loaded.get("proposal-1").status == "approved"
