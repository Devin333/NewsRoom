from __future__ import annotations

from typing import Any

from backend.foundation.models import BusinessPolicyProfile
from backend.foundation.primitives import build_stable_id
from backend.foundation.taxonomy import BoardType


DEFAULT_BOARD_POLICY_PARAMETERS: dict[str, dict[str, Any]] = {
    "ai_news": {
        "official_source_weight": 0.25,
        "impact_weight": 0.20,
        "freshness_weight": 0.20,
        "technology_relevance_weight": 0.15,
        "cross_board_relation_weight": 0.10,
        "novelty_weight": 0.10,
        "weak_evidence_penalty": 0.25,
        "top_requires_official_or_multi_source": True,
    },
    "project_radar": {
        "star_delta_weight": 0.20,
        "activity_weight": 0.20,
        "documentation_weight": 0.20,
        "technology_relevance_weight": 0.15,
        "relation_weight": 0.15,
        "maintainability_weight": 0.10,
        "top_requires_release_or_benchmark": True,
        "star_spike_penalty_without_evidence": 0.30,
    },
    "research": {
        "technology_novelty_weight": 0.25,
        "relevance_weight": 0.20,
        "implementation_potential_weight": 0.20,
        "related_project_weight": 0.15,
        "community_discussion_weight": 0.10,
        "freshness_weight": 0.10,
        "top_requires_benchmark_or_impl": True,
    },
    "community_pulse": {
        "volume_weight": 0.30,
        "quality_weight": 0.25,
        "expert_signal_weight": 0.20,
        "freshness_weight": 0.15,
        "relation_weight": 0.10,
        "noise_penalty": 0.30,
    },
    "cross_board": {
        "min_relation_count": 2,
        "min_evidence_count": 2,
        "require_multi_board_support": True,
        "unsupported_claim_block": True,
        "insight_confidence_threshold": 0.65,
    },
}


class PolicyLoader:
    def __init__(self, profiles: list[BusinessPolicyProfile] | None = None) -> None:
        self._profiles = profiles or default_policy_profiles()

    def active_profiles(
        self,
        *,
        board_type: BoardType | str | None = None,
        profile_type: str | None = None,
    ) -> list[BusinessPolicyProfile]:
        board_value = board_type.value if isinstance(board_type, BoardType) else board_type
        profiles = [profile for profile in self._profiles if profile.status == "active"]
        if board_value:
            profiles = [
                profile
                for profile in profiles
                if profile.metadata.get("board_type") == board_value or profile.profile_type.startswith(board_value)
            ]
        if profile_type:
            profiles = [profile for profile in profiles if profile.profile_type == profile_type]
        return profiles

    def require_active_profile(self, profile_type: str) -> BusinessPolicyProfile:
        matches = self.active_profiles(profile_type=profile_type)
        if not matches:
            raise LookupError(f"no active policy profile for {profile_type}")
        profile = matches[0]
        if not profile.version:
            raise ValueError(f"policy profile {profile.profile_id} has no version")
        return profile


def default_policy_profiles() -> list[BusinessPolicyProfile]:
    profiles: list[BusinessPolicyProfile] = []
    for board_type, parameters in DEFAULT_BOARD_POLICY_PARAMETERS.items():
        profile_type = f"{board_type}_ranking"
        profiles.append(
            BusinessPolicyProfile(
                profile_id=build_stable_id("policy", profile_type, "v1"),
                profile_type=profile_type,
                version="v1",
                name=f"{board_type.replace('_', ' ').title()} Ranking",
                description=f"Default final-target {board_type} ranking policy.",
                parameters=dict(parameters),
                status="active",
                metadata={"board_type": board_type},
            )
        )
    return profiles
