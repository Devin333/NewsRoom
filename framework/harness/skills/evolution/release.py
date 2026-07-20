from __future__ import annotations

from dataclasses import replace

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.authority import (
    ResolvedSkillReleaseAuthorization,
    SkillReleaseAuthorization,
    SkillReleaseAuthorityResolver,
    skill_package_hash,
)
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
    SkillVersionRef,
)


class VersionedSkillReleaseRegistry:
    """In-memory release contract; it is not a production release store."""

    production_ready = False

    def __init__(self, authority_resolver: SkillReleaseAuthorityResolver | None = None) -> None:
        self.authority_resolver = authority_resolver
        self.releases: dict[str, SkillRelease] = {}
        self.active_versions: dict[str, SkillVersionRef] = {}
        self.version_history: dict[str, list[SkillVersionRef]] = {}
        self.release_write_count = 0
        self.history_write_count = 0
        self.active_version_write_count = 0

    def prepare_release(self, candidate: SkillCandidate, decision: SkillPromotionDecision) -> SkillRelease:
        if not decision.is_approved:
            raise HarnessValidationError("only approved Harness decisions can prepare a skill release")
        if decision.candidate_id != candidate.candidate_id:
            raise HarnessValidationError("promotion decision does not match candidate")
        previous = self.active_versions.get(candidate.base_version.skill_name, candidate.base_version)
        package_hash = skill_package_hash(candidate)
        version = SkillVersionRef(
            skill_name=candidate.base_version.skill_name,
            version=decision.required_release_version or candidate.candidate_version or _next_minor(candidate.base_version.version),
            package_hash=package_hash,
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
            metadata={"versioned_release": True, "authority_required": True},
        )

    def bind_release(
        self,
        release: SkillRelease,
        authorization: SkillReleaseAuthorization,
    ) -> SkillRelease:
        record = self._resolve(authorization.authorization_ref)
        if record.authorization != authorization or record.release != release:
            raise _release_error(
                "skill_release_authority_mismatch",
                "release does not match the canonical authority record",
                authorization_ref=authorization.authorization_ref,
            )
        return _bound_release(record)

    def publish_release(self, release: SkillRelease) -> SkillRelease:
        authorization_ref = release.release_authorization_ref
        if authorization_ref is None:
            raise _release_error(
                "skill_release_authority_missing",
                "skill release publication requires a registered authority reference",
                release_id=release.release_id,
            )
        record = self._resolve(authorization_ref)
        expected = _bound_release(record)
        if release != expected:
            raise _release_error(
                "skill_release_authority_mismatch",
                "skill release does not match its resolved authority evidence",
                release_id=release.release_id,
                authorization_ref=authorization_ref,
            )
        existing = self.releases.get(release.release_id)
        if existing is not None:
            if existing != release:
                raise _release_error(
                    "skill_release_identity_collision",
                    "release id is already bound to a different authorized release",
                    release_id=release.release_id,
                )
            return existing

        self.releases[release.release_id] = release
        self.release_write_count += 1
        history = self.version_history.setdefault(release.version.skill_name, [])
        history.append(release.version)
        self.history_write_count += 1
        self.active_versions[release.version.skill_name] = release.version
        self.active_version_write_count += 1
        return release

    def rollback(self, rollback_plan: SkillRollbackPlan) -> SkillRollbackPlan:
        authorization_ref = rollback_plan.release_authorization_ref
        if authorization_ref is None or rollback_plan.side_effect_decision_ref is None:
            raise _release_error(
                "skill_rollback_authority_missing",
                "skill rollback requires the original release authority",
                release_id=rollback_plan.release_id,
            )
        release = self.releases.get(rollback_plan.release_id)
        if release is None:
            raise _release_error(
                "skill_rollback_release_missing",
                "skill rollback requires a published canonical release",
                release_id=rollback_plan.release_id,
            )
        record = self._resolve(authorization_ref)
        expected = _bound_release(record)
        if release != expected or rollback_plan != expected.rollback_plan:
            raise _release_error(
                "skill_rollback_authority_mismatch",
                "rollback plan does not match the authorized release",
                release_id=rollback_plan.release_id,
            )
        if rollback_plan.previous_version is not None:
            skill_name = rollback_plan.previous_version.skill_name
            current = self.active_versions.get(skill_name)
            if current == rollback_plan.previous_version:
                return replace(
                    rollback_plan,
                    metadata={**rollback_plan.metadata, "rolled_back": True},
                )
            if current != release.version:
                raise _release_error(
                    "skill_rollback_active_version_mismatch",
                    "rollback release is not the current active version",
                    release_id=rollback_plan.release_id,
                )
            self.active_versions[skill_name] = rollback_plan.previous_version
            self.active_version_write_count += 1
        return replace(rollback_plan, metadata={**rollback_plan.metadata, "rolled_back": True})

    def get_active_version(self, skill_name: str) -> SkillVersionRef | None:
        return self.active_versions.get(skill_name)

    def _resolve(self, authorization_ref: str) -> ResolvedSkillReleaseAuthorization:
        if self.authority_resolver is None:
            raise _release_error(
                "skill_release_authority_resolver_missing",
                "skill release registry has no authority resolver",
            )
        return self.authority_resolver.resolve(authorization_ref)


def _bound_release(record: ResolvedSkillReleaseAuthorization) -> SkillRelease:
    authorization = record.authorization
    decision = replace(
        record.promotion_decision,
        release_authorization_ref=authorization.authorization_ref,
    )
    rollback = replace(
        record.release.rollback_plan,
        release_authorization_ref=authorization.authorization_ref,
        side_effect_decision_ref=authorization.side_effect_decision_ref,
    )
    return replace(
        record.release,
        rollback_plan=rollback,
        promotion_decision=decision,
        release_authorization_ref=authorization.authorization_ref,
        side_effect_decision_ref=authorization.side_effect_decision_ref,
        idempotency_key=authorization.idempotency_key,
    )


def _next_minor(version: str) -> str:
    parts = str(version).split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return "0.1.0"
    return f"{parts[0]}.{int(parts[1]) + 1}.0"


def _release_error(code: str, message: str, **details) -> HarnessValidationError:
    return HarnessValidationError(message, code=code, details={"code": code, **details})


__all__ = ["VersionedSkillReleaseRegistry"]
