from __future__ import annotations

from hashlib import sha1
from typing import Any

from business.foundation.feedback.approval_state import APPLICABLE_STATUSES
from business.foundation.feedback.improvement_proposal import ImprovementProposal
from business.foundation.feedback.override_policy import BoardImprovementContext, ImprovementOverride, SUPPORTED_OVERRIDE_TYPES


class ImprovementApplier:
    def apply(
        self,
        proposals: list[ImprovementProposal],
        *,
        run_id: str,
        board_type: str,
    ) -> BoardImprovementContext:
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for proposal in proposals:
            if proposal.board_type != board_type:
                skipped.append({"proposal_id": proposal.proposal_id, "reason": "different_board", "status": proposal.status})
                continue
            if proposal.status not in APPLICABLE_STATUSES:
                skipped.append({"proposal_id": proposal.proposal_id, "reason": "not_approved", "status": proposal.status})
                continue
            if proposal.change_type not in SUPPORTED_OVERRIDE_TYPES:
                skipped.append({"proposal_id": proposal.proposal_id, "reason": "unsupported_change_type", "status": proposal.status})
                continue
            override = ImprovementOverride(
                override_id=_override_id(proposal),
                proposal_id=proposal.proposal_id,
                board_type=board_type,
                override_type=proposal.change_type,
                target_id=proposal.target_id,
                patch=dict(proposal.proposed_patch),
            )
            applied.append(override.to_dict())
        return BoardImprovementContext(
            run_id=run_id,
            board_type=board_type,
            applied_overrides=applied,
            skipped_overrides=skipped,
            proposal_ids=[proposal.proposal_id for proposal in proposals],
            measurement_plan={
                "compare_metrics": [
                    "quality_score",
                    "card_count",
                    "evidence_coverage",
                    "duplicate_rate",
                    "empty_output",
                    "subscription_match",
                ]
            },
        )


def _override_id(proposal: ImprovementProposal) -> str:
    digest = sha1(f"{proposal.proposal_id}|{proposal.change_type}|{proposal.target_id}".encode("utf-8")).hexdigest()[:12]
    return f"override_{digest}"


__all__ = ["ImprovementApplier"]
