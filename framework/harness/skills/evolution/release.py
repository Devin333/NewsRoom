from __future__ import annotations

from dataclasses import replace

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
    SkillVersionRef,
)


class VersionedSkillReleaseRegistry:
    def __init__(self) -> None:
        self.releases: dict[str, SkillRelease] = {}
        self.active_versions: dict[str, SkillVersionRef] = {}
        self.version_history: dict[str, list[SkillVersionRef]] = {}

    def prepare_release(self, candidate: SkillCandidate, decision: SkillPromotionDecision) -> SkillRelease:
        if not decision.is_approved:
            raise HarnessValidationError("only approved Harness decisions can prepare a skill release")
        previous = self.active_versions.get(candidate.base_version.skill_name, candidate.base_version)
        version = SkillVersionRef(
            skill_name=candidate.base_version.skill_name,
            version=decision.required_release_version or candidate.candidate_version or _next_minor(candidate.base_version.version),
            package_hash=candidate.manifest_snapshot.get("package_hash", f"sha256:{candidate.candidate_id}"),
            source_root=candidate.base_version.source_root,
            package_ref=candidate.package_ref or f"skill://candidate/{candidate.candidate_id}",
            status="active",
        )
        release_id = f"skill-release://{candidate.base_version.skill_name}/{version.version}"
        rollback = SkillRollbackPlan(
            release_id=release_id,
            previous_version=previous,
            triggers=("post_release_eval_failed", "quality_regression", "operator_request"),
            rollback_transcript_ref=f"skill-rollback-transcript://{candidate.candidate_id}",
        )
        return SkillRelease(
            release_id=release_id,
            candidate_id=candidate.candidate_id,
            version=version,
            rollback_plan=rollback,
            promotion_decision=decision,
            release_notes_ref=f"skill-release-notes://{candidate.candidate_id}",
            transcript_refs=(f"skill-promotion-transcript://{candidate.candidate_id}",),
            metadata={"versioned_release": True},
        )

    def publish_release(self, release: SkillRelease) -> SkillRelease:
        self.releases[release.release_id] = release
        history = self.version_history.setdefault(release.version.skill_name, [])
        history.append(release.version)
        self.active_versions[release.version.skill_name] = release.version
        return release

    def rollback(self, rollback_plan: SkillRollbackPlan) -> SkillRollbackPlan:
        if rollback_plan.previous_version is not None:
            self.active_versions[rollback_plan.previous_version.skill_name] = rollback_plan.previous_version
        return replace(rollback_plan, metadata={**rollback_plan.metadata, "rolled_back": True})

    def get_active_version(self, skill_name: str) -> SkillVersionRef | None:
        return self.active_versions.get(skill_name)


def _next_minor(version: str) -> str:
    parts = str(version).split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return "0.1.0"
    return f"{parts[0]}.{int(parts[1]) + 1}.0"


__all__ = ["VersionedSkillReleaseRegistry"]
