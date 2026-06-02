from __future__ import annotations

from typing import Any

from business.foundation.feedback.improvement_applier import ImprovementApplier
from business.foundation.feedback.improvement_proposal import ImprovementProposal
from business.foundation.feedback.override_policy import BoardImprovementContext


class ImprovementApplicationService:
    def __init__(
        self,
        *,
        proposal_store: Any,
        applier: ImprovementApplier | None = None,
    ) -> None:
        self.proposal_store = proposal_store
        self.applier = applier or ImprovementApplier()

    def proposals_for_board(self, board_type: str) -> list[ImprovementProposal]:
        return [
            proposal
            for proposal in self.proposal_store.list()
            if proposal.board_type == board_type
        ]

    def apply_approved_policy_experiments(
        self,
        *,
        run_id: str,
        board_type: str,
    ) -> BoardImprovementContext:
        return self.applier.apply(
            self.proposals_for_board(board_type),
            run_id=run_id,
            board_type=board_type,
        )

    def apply_approved(
        self,
        *,
        run_id: str,
        board_type: str,
    ) -> BoardImprovementContext:
        return self.apply_approved_policy_experiments(run_id=run_id, board_type=board_type)


__all__ = ["ImprovementApplicationService"]
