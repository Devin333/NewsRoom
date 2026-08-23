from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.fake import InMemoryHarnessSideEffectStore
from framework.harness.side_effects.models import (
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
)
from framework.harness.skills.evolution.authority import (
    InMemorySkillReleaseAuthorityResolver,
    SKILL_RELEASE_EFFECT_KIND,
    skill_candidate_ref,
    skill_evaluation_ref,
    skill_promotion_decision_ref,
    skill_promotion_gate_ref,
    skill_release_evidence_payload,
)
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
    """In-memory evolution contract used by tests; never a production release store."""

    production_ready = False

    def __init__(self) -> None:
        self.experience_store = InMemorySkillExperienceStore()
        self.candidate_store = InMemorySkillCandidateStore()
        self.static_validator = SkillStaticValidator(SkillStaticGateSuite())
        self.eval_runner = SkillEvalReplayRunner()
        self.sandbox_runner = SkillSandboxTrialRunner()
        self.promotion_decider = SkillPromotionDecider()
        self.side_effect_store = InMemoryHarnessSideEffectStore()
        self.release_authority_resolver = InMemorySkillReleaseAuthorityResolver(
            self.side_effect_store
        )
        self.release_registry = VersionedSkillReleaseRegistry(
            self.release_authority_resolver
        )
        self.patch_applier = SkillPatchApplier()
        self.evaluations: dict[str, SkillEvaluationResult] = {}
        self._prepared_releases: dict[str, SkillRelease] = {}
        self._authorized_decisions: dict[str, SkillPromotionDecision] = {}
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
            base_skill_name = str(request.get("skill_id", request.get("skill_name", "reader.repair")))
            base_version = str(request.get("base_version", "0.1.0"))
            base = SkillVersionRef(
                skill_name=base_skill_name,
                version=base_version,
                package_ref=str(request.get("package_ref", "skill://fake/base")),
                package_hash=str(
                    request.get(
                        "package_hash",
                        checksum_for(
                            {"skill_name": base_skill_name, "version": base_version}
                        ),
                    )
                ),
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
        package_hash = checksum_for(package_snapshot)
        candidate = SkillCandidate(
            candidate_id=candidate_id,
            base_version=base,
            candidate_version=str(request.get("candidate_version", "0.2.0")),
            patch_set=patch_set,
            manifest_snapshot={
                **manifest_snapshot,
                "package_hash": package_hash,
                "package_snapshot": package_snapshot,
            },
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
        evaluation_ref = skill_evaluation_ref(evaluation)
        cached = self._authorized_decisions.get(evaluation_ref)
        if cached is not None:
            return cached
        candidate = self.candidates[evaluation.candidate_id]
        decision = self.promotion_decider.decide(
            candidate,
            evaluation,
            approval_ref=candidate.metadata.get("approval_ref"),
            release_version=candidate.candidate_version or "0.2.0",
        )
        if decision.status == SkillPromotionStatus.PROMOTE:
            decision = replace(decision, status=SkillPromotionStatus.APPROVED)
        if decision.is_approved:
            decision = self._authorize_promotion(candidate, evaluation, decision)
            self._authorized_decisions[evaluation_ref] = decision
        self._event("skill_promotion_decided", decision.to_dict())
        return decision

    def promote_candidate(self, decision: SkillPromotionDecision) -> SkillRelease:
        if not decision.is_approved:
            raise HarnessValidationError("only approved decisions can promote candidates")
        authorization_ref = decision.release_authorization_ref
        if authorization_ref is None:
            raise HarnessValidationError(
                "promotion decision has no resolved release authority",
                code="skill_release_authority_missing",
            )
        release = self._prepared_releases.get(authorization_ref)
        if release is None or release.promotion_decision is None:
            raise HarnessValidationError(
                "promotion decision authority is not registered",
                code="skill_release_authority_missing",
            )
        if skill_promotion_decision_ref(decision) != skill_promotion_decision_ref(
            release.promotion_decision
        ):
            raise HarnessValidationError(
                "promotion decision does not match canonical release authority",
                code="skill_release_authority_mismatch",
            )
        published = self.release_registry.publish_release(release)
        candidate = self.candidates[published.candidate_id]
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

    def _authorize_promotion(
        self,
        candidate: SkillCandidate,
        evaluation: SkillEvaluationResult,
        decision: SkillPromotionDecision,
    ) -> SkillPromotionDecision:
        release = self.release_registry.prepare_release(candidate, decision)
        approval_ref = decision.approval_ref or checksum_for(
            {
                "policy": "skill_release_approval_not_required",
                "version": "1",
                "candidate_id": candidate.candidate_id,
            }
        )
        candidate_ref = skill_candidate_ref(candidate)
        evaluation_ref = skill_evaluation_ref(evaluation)
        gate_ref = skill_promotion_gate_ref(decision)
        effect_identity = {
            "candidate_ref": candidate_ref,
            "evaluation_ref": evaluation_ref,
            "release_id": release.release_id,
        }
        effect_digest = checksum_for(effect_identity).removeprefix("sha256:")
        graph_id = "fake-skill-evolution"
        graph_version = "1"
        graph_ref = f"{graph_id}@{graph_version}"
        graph_checksum = checksum_for({"graph_id": graph_id, "graph_version": graph_version})
        node_id = "skill_evolution.release"
        node_instance_id = f"fake-skill-node:{effect_digest}"
        activity_id = f"fake-skill-activity:{effect_digest}"
        intent = HarnessSideEffectIntent(
            effect_id=f"skill-release-effect:{effect_digest}",
            kind=SKILL_RELEASE_EFFECT_KIND,
            run_id="run://fake-skill-evolution",
            graph_id=graph_id,
            graph_version=graph_version,
            graph_ref=graph_ref,
            graph_checksum=graph_checksum,
            origin="worker",
            atomic_group=f"skill-release:{effect_digest}",
            identity_scope_ref=checksum_for({"scope": "fake-skill-evolution"}),
            subject_scope_ref=checksum_for(
                {"skill_name": candidate.base_version.skill_name}
            ),
            node_id=node_id,
            node_instance_id=node_instance_id,
            activity_id=activity_id,
            worker_result_ref=checksum_for(effect_identity),
            candidate_checksum=candidate_ref,
            handler=self.release_authority_resolver.handler,
            payload=skill_release_evidence_payload(
                candidate=candidate,
                evaluation=evaluation,
                promotion_decision=decision,
                release=release,
                approval_ref=approval_ref,
            ),
            candidate_refs=(release.version.package_ref or candidate.base_version.immutable_ref,),
        )
        side_effect_decision = HarnessSideEffectDecision(
            decision_id=f"skill-release-decision:{effect_digest}",
            intent_ref=intent.checksum,
            effect_id=intent.effect_id,
            kind=intent.kind,
            origin=intent.origin,
            run_id=intent.run_id,
            graph_id=intent.graph_id,
            graph_version=intent.graph_version,
            graph_ref=intent.graph_ref,
            graph_checksum=intent.graph_checksum,
            handler=intent.handler,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            idempotency_key=intent.idempotency_key,
            command_ordinal=1,
            causation_id="fake-skill-evolution:promotion-gate",
            disposition=HarnessSideEffectDisposition.ACCEPTED,
            node_id=intent.node_id,
            node_instance_id=intent.node_instance_id,
            activity_id=intent.activity_id,
            attempt=intent.attempt,
            worker_result_ref=intent.worker_result_ref,
            gate_refs=("skill_promotion@1",),
            gate_result_refs=(gate_ref,),
            aggregate_verdict_ref=checksum_for(
                {"promotion_gate_ref": gate_ref, "passed": True}
            ),
            approval_evidence_ref=approval_ref,
            budget_ref=checksum_for(
                {"contract": "fake-skill-evolution", "effect_attempt_limit": 1}
            ),
        )
        canonical_decision = self.side_effect_store.put_decision(side_effect_decision)
        authorization = self.release_authority_resolver.register(
            candidate=candidate,
            evaluation=evaluation,
            promotion_decision=decision,
            release=release,
            side_effect_intent=intent,
            side_effect_decision_ref=canonical_decision.checksum,
        )
        bound_release = self.release_registry.bind_release(release, authorization)
        self._prepared_releases[authorization.authorization_ref] = bound_release
        assert bound_release.promotion_decision is not None
        return bound_release.promotion_decision


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
