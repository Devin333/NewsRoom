from __future__ import annotations

from dataclasses import replace

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillExperience,
    SkillPatchSet,
    SkillPromotionDecision,
    SkillPromotionStatus,
    SkillRelease,
    SkillRollbackPlan,
    SkillVersionRef,
)


class FakeSkillEvolutionPort:
    def __init__(self) -> None:
        self.experiences: dict[str, SkillExperience] = {}
        self.candidates: dict[str, SkillCandidate] = {}
        self.evaluations: dict[str, SkillEvaluationResult] = {}
        self.releases: dict[str, SkillRelease] = {}
        self.active_versions: dict[str, SkillVersionRef] = {}

    def collect_experience(self, request: dict) -> SkillExperience:
        experience = SkillExperience(
            experience_id=str(request.get("experience_id", f"experience://fake/{len(self.experiences) + 1}")),
            source=str(request.get("source", "business_run")),
            summary=str(request.get("summary", "Fake skill experience")),
            evidence_refs=tuple(request.get("evidence_refs", ())),
            metadata=dict(request.get("metadata", {})),
        )
        self.experiences[experience.experience_id] = experience
        return experience

    def propose_candidate(self, request: dict) -> SkillCandidate:
        base = request.get("base_version")
        if not isinstance(base, SkillVersionRef):
            base = SkillVersionRef(
                skill_id=str(request.get("skill_id", "skill.fake")),
                version=str(request.get("base_version", "0.1.0")),
                package_ref=str(request.get("package_ref", "skill://fake/base")),
            )
        patch_set = SkillPatchSet(
            patch_id=str(request.get("patch_id", f"patch://fake/{len(self.candidates) + 1}")),
            target=base,
            operations=tuple(request.get("operations", ({"op": "replace", "path": "/instructions", "value": "candidate"},))),
            rationale=request.get("rationale", "fake candidate"),
        )
        candidate = SkillCandidate(
            candidate_id=str(request.get("candidate_id", f"candidate://fake/{len(self.candidates) + 1}")),
            base_version=base,
            patch_set=patch_set,
            experiences=tuple(self.experiences.values()),
            metadata=dict(request.get("metadata", {})),
        )
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    def evaluate_candidate(self, candidate: SkillCandidate) -> SkillEvaluationResult:
        evaluation = SkillEvaluationResult(
            candidate_id=candidate.candidate_id,
            passed=True,
            score=0.8,
            eval_case_count=1,
            metrics={"fake": True},
        )
        self.evaluations[candidate.candidate_id] = evaluation
        return evaluation

    def decide_promotion(self, evaluation: SkillEvaluationResult) -> SkillPromotionDecision:
        status = SkillPromotionStatus.APPROVED if evaluation.passed and evaluation.score >= 0.7 else SkillPromotionStatus.REJECTED
        return SkillPromotionDecision(
            candidate_id=evaluation.candidate_id,
            status=status,
            reasons=("fake held-out eval passed",) if status == SkillPromotionStatus.APPROVED else ("fake eval failed",),
            required_release_version="0.2.0" if status == SkillPromotionStatus.APPROVED else None,
        )

    def promote_candidate(self, decision: SkillPromotionDecision) -> SkillRelease:
        if decision.status != SkillPromotionStatus.APPROVED:
            raise HarnessValidationError("only approved decisions can promote candidates")
        candidate = self.candidates[decision.candidate_id]
        version = SkillVersionRef(
            skill_id=candidate.base_version.skill_id,
            version=decision.required_release_version or "0.2.0",
            package_ref=f"skill://fake/release/{candidate.candidate_id}",
        )
        rollback = SkillRollbackPlan(
            release_id=f"release://fake/{len(self.releases) + 1}",
            previous_version=candidate.base_version,
            triggers=("quality_regression", "operator_request"),
        )
        release = SkillRelease(
            release_id=rollback.release_id,
            candidate_id=candidate.candidate_id,
            version=version,
            rollback_plan=rollback,
        )
        self.releases[release.release_id] = release
        self.active_versions[version.skill_id] = version
        return release

    def rollback_release(self, release: SkillRelease) -> SkillRollbackPlan:
        if release.rollback_plan.previous_version is not None:
            self.active_versions[release.version.skill_id] = release.rollback_plan.previous_version
        return replace(release.rollback_plan, metadata={**release.rollback_plan.metadata, "rolled_back": True})


__all__ = ["FakeSkillEvolutionPort"]
