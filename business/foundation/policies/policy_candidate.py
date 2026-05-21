from __future__ import annotations

from business.foundation.models import (
    BusinessLearningSignal,
    BusinessPolicyCandidate,
    BusinessPolicyProfile,
)
from business.foundation.primitives import build_stable_id


def build_policy_candidate(
    learning_signal: BusinessLearningSignal,
    base_profile: BusinessPolicyProfile,
) -> BusinessPolicyCandidate:
    profile = BusinessPolicyProfile(
        profile_id=base_profile.profile_id,
        profile_type=base_profile.profile_type,
        version=f"{base_profile.version}-candidate",
        name=f"{base_profile.name} Candidate",
        description=base_profile.description,
        parameters={**base_profile.parameters, **learning_signal.suggested_adjustment},
        based_on_feedback_ids=list(learning_signal.related_feedback_ids),
        based_on_run_ids=list(base_profile.based_on_run_ids),
        based_on_manifest_refs=list(base_profile.based_on_manifest_refs),
        status="candidate",
        activation_rule=dict(base_profile.activation_rule),
        rollback_ref=base_profile.rollback_ref,
        metadata={**base_profile.metadata, "source_learning_signal_id": learning_signal.signal_id},
    )
    return BusinessPolicyCandidate(
        candidate_id=build_stable_id("policy_candidate", profile.profile_id, profile.version, learning_signal.signal_id),
        profile=profile,
        based_on_learning_signal_ids=[learning_signal.signal_id],
    )


__all__ = ["build_policy_candidate"]
