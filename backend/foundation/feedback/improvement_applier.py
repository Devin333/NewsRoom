from __future__ import annotations

from hashlib import sha1
from typing import Any

from backend.foundation.feedback.approval_state import APPLICABLE_STATUSES
from backend.foundation.feedback.improvement_proposal import ImprovementProposal
from backend.foundation.feedback.policy_experiment import (
    AppliedPolicyExperiment,
    PolicyExperimentApplicationContext,
    PolicyExperimentProfile,
    is_legacy_policy_experiment_change_type,
    policy_experiment_target_type,
)


class ImprovementApplier:
    def apply(
        self,
        proposals: list[ImprovementProposal],
        *,
        run_id: str,
        board_type: str,
    ) -> PolicyExperimentApplicationContext:
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
        return PolicyExperimentApplicationContext(
            run_id=run_id,
            board_type=board_type,
            applied_policy_experiments=applied,
            skipped_policy_experiments=skipped,
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
    if not is_legacy_policy_experiment_change_type(proposal.change_type):
        return None
    parameters = proposal.policy_experiment_parameters
    return PolicyExperimentProfile(
        profile_id=f"legacy_{proposal.change_type}_{proposal.target_id}",
        board_type=proposal.board_type,
        target_type=policy_experiment_target_type(proposal.change_type),
        target_id=proposal.target_id,
        parameters=parameters,
        rationale=str(parameters.get("reason") or "legacy approved improvement proposal"),
        suggested_action=str(parameters.get("suggested_action") or "run as policy experiment"),
    )


def _experiment_id(proposal: ImprovementProposal, profile: PolicyExperimentProfile) -> str:
    digest = sha1(f"{proposal.proposal_id}|{profile.profile_id}|{profile.target_id}".encode("utf-8")).hexdigest()[:12]
    return f"experiment_{digest}"


__all__ = ["ImprovementApplier"]
