from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.candidate import InMemorySkillCandidateStore, SkillPatchApplier
from framework.harness.skills.evolution.evaluator import SkillEvalReplayRunner, SkillSandboxTrialRunner, SkillStaticValidator
from framework.harness.skills.evolution.experience import InMemorySkillExperienceStore
from framework.harness.skills.evolution.gates import SkillStaticGateSuite
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillCandidateStatus,
    SkillEvaluationResult,
    SkillExperience,
    SkillExperienceOutcome,
    SkillPatchSet,
    SkillPromotionDecision,
    SkillPromotionStatus,
    SkillRelease,
    SkillRollbackPlan,
    SkillVersionRef,
)
from framework.harness.skills.evolution.promotion import SkillPromotionDecider
from framework.harness.skills.evolution.release import VersionedSkillReleaseRegistry


class FakeSkillEvolutionPort:
    def __init__(self) -> None:
        self.experience_store = InMemorySkillExperienceStore()
        self.candidate_store = InMemorySkillCandidateStore()
        self.static_validator = SkillStaticValidator(SkillStaticGateSuite())
        self.eval_runner = SkillEvalReplayRunner()
        self.sandbox_runner = SkillSandboxTrialRunner()
        self.promotion_decider = SkillPromotionDecider()
        self.release_registry = VersionedSkillReleaseRegistry()
        self.patch_applier = SkillPatchApplier()
        self.evaluations: dict[str, SkillEvaluationResult] = {}
        self.events: list[dict[str, Any]] = []

    @property
    def experiences(self) -> dict[str, SkillExperience]:
        return self.experience_store.experiences

    @property
    def candidates(self) -> dict[str, SkillCandidate]:
        return self.candidate_store.candidates

    @property
    def releases(self) -> dict[str, SkillRelease]:
        return self.release_registry.releases

    @property
    def active_versions(self) -> dict[str, SkillVersionRef]:
        return self.release_registry.active_versions

    def collect_experience(self, request: dict) -> SkillExperience:
        experience = SkillExperience(
            experience_id=str(request.get("experience_id", f"experience://fake/{len(self.experiences) + 1}")),
            run_id=request.get("run_id", "run://fake-skill-evolution"),
            step_id=request.get("step_id", "step://collect-experience"),
            skill_name=request.get("skill_name", request.get("skill_id")),
            skill_version=request.get("skill_version", "0.1.0"),
            domain=request.get("domain", "research"),
            task_type=request.get("task_type", "reader_repair"),
            input_refs=tuple(request.get("input_refs", ())),
            output_refs=tuple(request.get("output_refs", ())),
            transcript_refs=tuple(request.get("transcript_refs", ("transcript://fake-skill-experience",))),
            gate_results=tuple(request.get("gate_results", ())),
            score=request.get("score", 0.8),
            outcome=request.get("outcome", SkillExperienceOutcome.SUCCESS),
            failure_tags=tuple(request.get("failure_tags", ())),
            evidence_refs=tuple(request.get("evidence_refs", ())),
            source=str(request.get("source", "business_run")),
            summary=str(request.get("summary", "Reader repair should preserve evidence refs.")),
            metadata=dict(request.get("metadata", {})),
        )
        self._event("skill_experience_collected", experience.to_dict())
        return self.experience_store.append_experience(experience)

    def propose_candidate(self, request: dict) -> SkillCandidate:
        base = request.get("base_version")
        if not isinstance(base, SkillVersionRef):
            base = SkillVersionRef(
                skill_name=str(request.get("skill_id", request.get("skill_name", "reader.repair"))),
                version=str(request.get("base_version", "0.1.0")),
                package_ref=str(request.get("package_ref", "skill://fake/base")),
                package_hash=str(request.get("package_hash", "sha256:fake-base")),
                source_root=str(request.get("source_root", "skills/reader.repair")),
            )
        candidate_id = str(request.get("candidate_id", f"candidate://fake/{len(self.candidates) + 1}"))
        patch_set = SkillPatchSet(
            patch_id=str(request.get("patch_id", f"patch://fake/{len(self.candidates) + 1}")),
            candidate_id=candidate_id,
            base_skill=base,
            operations=tuple(
                request.get(
                    "operations",
                    (
                        {
                            "op": "replace_section",
                            "path": "SKILL.md#retrieval-strategy",
                            "value": "Preserve method, table, and citation lineage before repair synthesis.",
                            "reason": "failed repair cases lost source refs",
                        },
                    ),
                )
            ),
            patch_budget=dict(request.get("patch_budget", {"max_patch_operations": 6, "max_changed_files": 4})),
            changed_files=tuple(request.get("changed_files", ("SKILL.md",))),
            changed_sections=tuple(request.get("changed_sections", ("retrieval-strategy",))),
            optimizer_worker_ref=str(request.get("optimizer_worker_ref", "worker://fake-skill-optimizer")),
            reasoning_summary=str(request.get("rationale", "candidate improves reader repair evidence preservation")),
        )
        manifest_snapshot = _manifest_snapshot(base, request)
        package_snapshot = self.patch_applier.apply_patch(patch_set, package_snapshot={"SKILL.md": "base instructions"})
        candidate = SkillCandidate(
            candidate_id=candidate_id,
            base_version=base,
            candidate_version=str(request.get("candidate_version", "0.2.0")),
            patch_set=patch_set,
            manifest_snapshot={**manifest_snapshot, "package_hash": f"sha256:{candidate_id}", "package_snapshot": package_snapshot},
            package_ref=str(request.get("candidate_package_ref", f"skill://fake/candidate/{candidate_id}")),
            experiences=tuple(self.experiences.values()),
            metadata=dict(request.get("metadata", {})),
        )
        validation = self.static_validator.validate(candidate)
        candidate = replace(
            candidate,
            status=SkillCandidateStatus.EVAL_READY if validation.passed else SkillCandidateStatus.STATIC_REJECTED,
            static_gate_results=validation.gate_results,
        )
        if validation.passed:
            self.candidate_store.save_candidate(candidate)
        else:
            self.candidate_store.save_rejected(candidate, "; ".join(validation.issues) or "static gates failed")
        self._event("skill_candidate_proposed", candidate.to_dict())
        return candidate

    def evaluate_candidate(self, candidate: SkillCandidate) -> SkillEvaluationResult:
        if candidate.status == SkillCandidateStatus.STATIC_REJECTED:
            evaluation = SkillEvaluationResult(
                candidate_id=candidate.candidate_id,
                passed=False,
                score=0.0,
                baseline_score=0.0,
                held_out_score=0.0,
                minimum_improvement=0.01,
                regression_tolerance=0.0,
                eval_case_count=1,
                issues=("static gates failed",),
            )
        else:
            evaluation = self.eval_runner.run_eval_suite(
                candidate,
                {
                    "baseline_score": candidate.metadata.get("baseline_score", 0.7),
                    "candidate_score": candidate.metadata.get("candidate_score", 0.82),
                    "held_out_score": candidate.metadata.get("held_out_score", 0.82),
                    "minimum_improvement": candidate.metadata.get("minimum_improvement", 0.02),
                    "regression_tolerance": candidate.metadata.get("regression_tolerance", 0.0),
                    "metrics": candidate.metadata.get("metrics", {"evidence_coverage": 0.9}),
                    "max_eval_cases": 3,
                },
            )
        self.evaluations[candidate.candidate_id] = evaluation
        updated = self.eval_runner.attach_result(candidate, evaluation)
        self.candidate_store.save_candidate(updated)
        self._event("skill_candidate_evaluated", evaluation.to_dict())
        return evaluation

    def decide_promotion(self, evaluation: SkillEvaluationResult) -> SkillPromotionDecision:
        candidate = self.candidates[evaluation.candidate_id]
        decision = self.promotion_decider.decide(
            candidate,
            evaluation,
            approval_ref=candidate.metadata.get("approval_ref"),
            release_version=candidate.candidate_version or "0.2.0",
        )
        if decision.status == SkillPromotionStatus.PROMOTE:
            decision = replace(decision, status=SkillPromotionStatus.APPROVED)
        self._event("skill_promotion_decided", decision.to_dict())
        return decision

    def promote_candidate(self, decision: SkillPromotionDecision) -> SkillRelease:
        if not decision.is_approved:
            raise HarnessValidationError("only approved decisions can promote candidates")
        candidate = self.candidates[decision.candidate_id]
        release = self.release_registry.prepare_release(candidate, decision)
        published = self.release_registry.publish_release(release)
        self.candidate_store.save_candidate(replace(candidate, status=SkillCandidateStatus.PROMOTED, promotion_decision=decision))
        self._event("skill_release_published", published.to_dict())
        return published

    def rollback_release(self, release: SkillRelease) -> SkillRollbackPlan:
        rollback = self.release_registry.rollback(release.rollback_plan)
        candidate = self.candidates.get(release.candidate_id)
        if candidate is not None:
            self.candidate_store.save_candidate(replace(candidate, status=SkillCandidateStatus.ROLLED_BACK))
        self._event("skill_release_rolled_back", rollback.to_dict())
        return rollback

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append({"event_type": event_type, "payload": payload})


def _manifest_snapshot(base: SkillVersionRef, request: dict) -> dict[str, Any]:
    return {
        "files": list(request.get("files", ("SKILL.md", "schemas/input.json", "schemas/output.json"))),
        "metadata": {
            "name": base.skill_name,
            "version": base.version,
            "risk_level": request.get("risk_level", "medium"),
            "owner": request.get("owner", "harness"),
            "allowed_tools": list(request.get("allowed_tools", ("llm", "schema_validator"))),
            "quality_gates": list(request.get("quality_gates", ("schema_valid", "evidence_required", "no_empty_output"))),
            "input_schema": request.get("input_schema", "schemas/input.json"),
            "output_schema": request.get("output_schema", "schemas/output.json"),
        },
        "input_schema": request.get("input_schema", "schemas/input.json"),
        "output_schema": request.get("output_schema", "schemas/output.json"),
    }


__all__ = ["FakeSkillEvolutionPort"]
