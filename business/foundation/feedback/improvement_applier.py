from __future__ import annotations

from hashlib import sha1
from typing import Any

from business.foundation.feedback.approval_state import APPLICABLE_STATUSES
from business.foundation.feedback.improvement_proposal import ImprovementProposal
from business.foundation.feedback.override_policy import BoardImprovementContext, SUPPORTED_OVERRIDE_TYPES
from business.foundation.feedback.policy_experiment import (
    AppliedPolicyExperiment,
    PolicyExperimentProfile,
    policy_experiment_target_type,
)


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
            profile = proposal.experiment_profile or _legacy_profile(proposal)
            if profile is None:
                skipped.append({"proposal_id": proposal.proposal_id, "reason": "unsupported_change_type", "status": proposal.status})
                continue
            applied.append(
                AppliedPolicyExperiment(
                    experiment_id=_experiment_id(proposal, profile),
                    proposal_id=proposal.proposal_id,
                    board_type=board_type,
                    profile_id=profile.profile_id,
                    target_type=profile.target_type,
                    target_id=profile.target_id,
                    parameters=dict(profile.parameters),
                ).to_dict()
            )
        return BoardImprovementContext(
            run_id=run_id,
            board_type=board_type,
            applied_overrides=applied,
            applied_policy_experiments=applied,
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


def _legacy_profile(proposal: ImprovementProposal) -> PolicyExperimentProfile | None:
    if proposal.change_type not in SUPPORTED_OVERRIDE_TYPES:
        return None
    return PolicyExperimentProfile(
        profile_id=f"legacy_{proposal.change_type}_{proposal.target_id}",
        board_type=proposal.board_type,
        target_type=policy_experiment_target_type(proposal.change_type),
        target_id=proposal.target_id,
        parameters=dict(proposal.proposed_patch),
        rationale=str(proposal.proposed_patch.get("reason") or "legacy approved improvement proposal"),
        suggested_action=str(proposal.proposed_patch.get("suggested_action") or "run as policy experiment"),
    )


def _experiment_id(proposal: ImprovementProposal, profile: PolicyExperimentProfile) -> str:
    digest = sha1(f"{proposal.proposal_id}|{profile.profile_id}|{profile.target_id}".encode("utf-8")).hexdigest()[:12]
    return f"experiment_{digest}"


__all__ = ["ImprovementApplier"]
