from __future__ import annotations

from business.foundation.feedback import ImprovementProposal, LocalJsonImprovementProposalStore


def test_local_json_proposal_store_persists_save_round_trip(tmp_path) -> None:
    store = LocalJsonImprovementProposalStore(tmp_path / "proposals.json")
    store.save(_proposal("proposal-save"))

    loaded = LocalJsonImprovementProposalStore(tmp_path / "proposals.json")
    proposal = loaded.get("proposal-save")
    assert proposal.status == "proposed"
    assert proposal.policy_experiment_parameters == {"weight": 1.2}


def test_local_json_proposal_store_persists_approved_status(tmp_path) -> None:
    store = LocalJsonImprovementProposalStore(tmp_path)
    store.save(_proposal("proposal-approved"))
    store.approve("proposal-approved")

    loaded = LocalJsonImprovementProposalStore(tmp_path)
    assert loaded.get("proposal-approved").status == "approved"
    assert [proposal.proposal_id for proposal in loaded.list(status="approved")] == [
        "proposal-approved"
    ]


def test_local_json_proposal_store_persists_applied_status(tmp_path) -> None:
    path = tmp_path / "nested" / "improvement_proposals.json"
    store = LocalJsonImprovementProposalStore(path)
    store.save(_proposal("proposal-applied"))
    store.approve("proposal-applied")
    store.mark_applied("proposal-applied")

    loaded = LocalJsonImprovementProposalStore(path)
    assert loaded.get("proposal-applied").status == "applied"
    assert loaded.list(status="approved") == []


def test_proposal_restores_legacy_parameters_from_formal_field() -> None:
    proposal = ImprovementProposal.from_dict(
        {
            "proposal_id": "proposal-formal",
            "recommendation_id": "rec-formal",
            "board_type": "ai_news",
            "change_type": "ranking_weight_override",
            "target_type": "ranking_weight_override",
            "target_id": "freshness",
            "policy_experiment_parameters": {"weight": 1.4},
            "risk_level": "medium",
            "requires_approval": True,
            "status": "proposed",
        }
    )

    assert proposal.policy_experiment_parameters == {"weight": 1.4}
    assert proposal.proposed_patch == {"weight": 1.4}
    serialized = proposal.to_dict()
    assert serialized["policy_experiment_parameters"] == {"weight": 1.4}
    assert "proposed_patch" not in serialized


def _proposal(proposal_id: str) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=proposal_id,
        recommendation_id=f"rec-{proposal_id}",
        board_type="ai_news",
        change_type="ranking_weight_override",
        target_type="ranking_weight_override",
        target_id="freshness",
        policy_experiment_parameters={"weight": 1.2},
        risk_level="medium",
        requires_approval=True,
        status="proposed",
    )
