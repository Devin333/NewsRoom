from __future__ import annotations

from dataclasses import dataclass

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    InMemoryHarnessSideEffectStore,
    InMemorySkillReleaseAuthorityResolver,
    SkillCandidate,
    SkillEvalReplayRunner,
    SkillEvaluationResult,
    SkillPatchSet,
    SkillPromotionDecider,
    SkillPromotionDecision,
    SkillRelease,
    SkillReleaseAuthorization,
    SkillVersionRef,
    VersionedSkillReleaseRegistry,
    skill_candidate_ref,
    skill_promotion_gate_ref,
    skill_release_evidence_payload,
)


@dataclass(frozen=True)
class AuthorizedReleaseFixture:
    candidate: SkillCandidate
    evaluation: SkillEvaluationResult
    decision: SkillPromotionDecision
    release: SkillRelease
    authority: SkillReleaseAuthorization
    registry: VersionedSkillReleaseRegistry
    resolver: InMemorySkillReleaseAuthorityResolver
    side_effect_store: InMemoryHarnessSideEffectStore


def authorized_release_fixture(*, release_version: str = "1.1.0") -> AuthorizedReleaseFixture:
    candidate = _candidate()
    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {
            "baseline_score": 0.7,
            "candidate_score": 0.86,
            "held_out_score": 0.86,
            "minimum_improvement": 0.05,
        },
    )
    decision = SkillPromotionDecider().decide(
        candidate,
        evaluation,
        release_version=release_version,
    )
    registry = VersionedSkillReleaseRegistry()
    release = registry.prepare_release(candidate, decision)
    side_effect_store = InMemoryHarnessSideEffectStore()
    resolver = InMemorySkillReleaseAuthorityResolver(side_effect_store)
    registry.authority_resolver = resolver
    approval_ref = checksum_for({"policy": "skill-release-not-required", "candidate": candidate.candidate_id})
    intent = HarnessSideEffectIntent(
        effect_id="skill-release-effect:fixture",
        kind="skill_release",
        run_id="run://skill-release-fixture",
        origin="worker",
        atomic_group="skill-release:fixture",
        identity_scope_ref=checksum_for({"scope": "fixture"}),
        subject_scope_ref=checksum_for({"skill_name": candidate.base_version.skill_name}),
        step_id="skill_evolution.release",
        worker_result_ref=checksum_for({"candidate": candidate.candidate_id}),
        candidate_checksum=skill_candidate_ref(candidate),
        handler=resolver.handler,
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
        decision_id="skill-release-decision:fixture",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        handler=intent.handler,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=1,
        causation_id="fixture:promotion",
        disposition=HarnessSideEffectDisposition.ACCEPTED,
        step_id=intent.step_id,
        worker_result_ref=intent.worker_result_ref,
        gate_refs=("skill_promotion@1",),
        gate_result_refs=(skill_promotion_gate_ref(decision),),
        aggregate_verdict_ref=checksum_for({"passed": True}),
        approval_evidence_ref=approval_ref,
        budget_ref=checksum_for({"effect_attempt_limit": 1}),
    )
    side_effect_store.put_decision(side_effect_decision)
    authority = resolver.register(
        candidate=candidate,
        evaluation=evaluation,
        promotion_decision=decision,
        release=release,
        side_effect_intent=intent,
        side_effect_decision_ref=side_effect_decision.checksum,
    )
    bound_release = registry.bind_release(release, authority)
    assert bound_release.promotion_decision is not None
    return AuthorizedReleaseFixture(
        candidate=candidate,
        evaluation=evaluation,
        decision=bound_release.promotion_decision,
        release=bound_release,
        authority=authority,
        registry=registry,
        resolver=resolver,
        side_effect_store=side_effect_store,
    )


def _candidate() -> SkillCandidate:
    base = SkillVersionRef(skill_name="reader.repair", version="1.0.0", package_ref="skills/reader")
    patch = SkillPatchSet(
        patch_id="patch-release-fixture",
        base_skill=base,
        operations=({"op": "replace", "path": "SKILL.md", "value": "new instructions"},),
    )
    return SkillCandidate(
        candidate_id="candidate-release-fixture",
        base_version=base,
        candidate_version="1.1.0",
        patch_set=patch,
        manifest_snapshot={
            "files": ["SKILL.md", "schemas/input.json", "schemas/output.json"],
            "metadata": {
                "name": "reader.repair",
                "version": "1.1.0",
                "risk_level": "medium",
                "owner": "harness",
                "allowed_tools": ["llm", "schema_validator"],
                "quality_gates": ["schema_valid", "evidence_required", "no_empty_output"],
                "input_schema": "schemas/input.json",
                "output_schema": "schemas/output.json",
            },
        },
    )


__all__ = ["AuthorizedReleaseFixture", "authorized_release_fixture"]
