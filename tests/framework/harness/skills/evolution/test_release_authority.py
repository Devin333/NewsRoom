from __future__ import annotations

from dataclasses import replace

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    FakeSkillEvolutionPort,
    HarnessBudget,
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessSideEffectHandlerReference,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerType,
    InMemoryHarnessEventPort,
    InMemorySkillReleaseAuthorityResolver,
    SkillPromotionDecision,
    skill_candidate_ref,
    skill_evaluation_ref,
    skill_package_hash,
    skill_promotion_decision_ref,
    skill_promotion_gate_ref,
    skill_rollback_plan_ref,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from tests.framework.harness.skills.evolution._authority_fixtures import (
    AuthorizedReleaseFixture,
    authorized_release_fixture,
)


def test_release_authority_resolves_every_required_provenance_ref() -> None:
    fixture = authorized_release_fixture()
    resolved = fixture.resolver.resolve(fixture.authority.authorization_ref)

    assert resolved.authorization == fixture.authority
    assert fixture.authority.candidate_ref == skill_candidate_ref(fixture.candidate)
    assert fixture.authority.evaluation_ref == skill_evaluation_ref(fixture.evaluation)
    assert fixture.authority.promotion_decision_ref == skill_promotion_decision_ref(
        fixture.decision
    )
    assert fixture.authority.promotion_gate_ref == skill_promotion_gate_ref(
        fixture.decision
    )
    assert fixture.authority.package_hash == skill_package_hash(fixture.candidate)
    assert fixture.authority.rollback_plan_ref == skill_rollback_plan_ref(
        fixture.release.rollback_plan
    )
    assert fixture.authority.side_effect_decision_ref == resolved.side_effect_decision.checksum
    assert fixture.authority.handler == HarnessSideEffectHandlerReference.parse(
        "harness.skill.release@1"
    )
    assert fixture.release.release_authorization_ref == fixture.authority.authorization_ref
    assert fixture.release.idempotency_key == fixture.authority.idempotency_key
    assert fixture.resolver.production_ready is False
    assert fixture.registry.production_ready is False


@pytest.mark.parametrize(
    "tamper",
    (
        lambda fixture: replace(fixture.release, candidate_id="candidate-forged"),
        lambda fixture: replace(
            fixture.release,
            version=replace(
                fixture.release.version,
                package_hash=checksum_for({"package": "forged"}),
            ),
        ),
        lambda fixture: replace(
            fixture.release,
            version=replace(fixture.release.version, version="9.9.9"),
        ),
        lambda fixture: replace(
            fixture.release,
            rollback_plan=replace(
                fixture.release.rollback_plan,
                triggers=("forged",),
            ),
        ),
        lambda fixture: replace(
            fixture.release,
            side_effect_decision_ref=checksum_for({"decision": "forged"}),
        ),
        lambda fixture: replace(
            fixture.release,
            idempotency_key="forged-idempotency-key",
        ),
        lambda fixture: replace(
            fixture.release,
            promotion_decision=replace(
                fixture.decision,
                reasons=("caller says approved",),
            ),
        ),
    ),
)
def test_tampered_bound_release_fails_before_any_registry_write(tamper) -> None:
    fixture = authorized_release_fixture()

    with pytest.raises(HarnessValidationError):
        fixture.registry.publish_release(tamper(fixture))

    _assert_zero_release_writes(fixture)


@pytest.mark.parametrize(
    "tamper",
    (
        lambda decision: SkillPromotionDecision(
            candidate_id=decision.candidate_id,
            status="approved",
        ),
        lambda decision: replace(decision, candidate_id="candidate-other"),
        lambda decision: replace(decision, reasons=("forged",)),
        lambda decision: replace(decision, required_release_version="9.9.9"),
        lambda decision: replace(
            decision,
            gate_results=({"gate": "skill_promotion", "passed": False},),
        ),
        lambda decision: replace(
            decision,
            approval_ref=checksum_for({"approval": "forged"}),
        ),
        lambda decision: replace(
            decision,
            release_authorization_ref=checksum_for({"authority": "unknown"}),
        ),
    ),
)
def test_forged_promotion_objects_cannot_use_fake_authority(tamper) -> None:
    evolution = FakeSkillEvolutionPort()
    candidate = evolution.propose_candidate({"skill_id": "reader.repair"})
    evaluation = evolution.evaluate_candidate(candidate)
    canonical = evolution.decide_promotion(evaluation)

    with pytest.raises(HarnessValidationError):
        evolution.promote_candidate(tamper(canonical))

    assert evolution.releases == {}
    assert evolution.release_registry.version_history == {}
    assert evolution.active_versions == {}
    assert evolution.release_registry.release_write_count == 0
    assert evolution.release_registry.history_write_count == 0
    assert evolution.release_registry.active_version_write_count == 0


def test_resolver_rechecks_canonical_side_effect_decision_before_publish() -> None:
    fixture = authorized_release_fixture()
    canonical = fixture.resolver.resolve(
        fixture.authority.authorization_ref
    ).side_effect_decision
    tampered = replace(
        canonical,
        approval_evidence_ref=checksum_for({"approval": "other"}),
        checksum=None,
    )
    fixture.side_effect_store.decisions_by_ref[
        fixture.authority.side_effect_decision_ref
    ] = tampered

    with pytest.raises(HarnessValidationError):
        fixture.registry.publish_release(fixture.release)

    _assert_zero_release_writes(fixture)


def test_fake_release_authority_creation_is_idempotent() -> None:
    evolution = FakeSkillEvolutionPort()
    candidate = evolution.propose_candidate({"skill_id": "reader.repair"})
    evaluation = evolution.evaluate_candidate(candidate)

    first = evolution.decide_promotion(evaluation)
    second = evolution.decide_promotion(evaluation)

    assert first == second
    assert evolution.side_effect_store.decision_write_count == 1
    assert evolution.release_authority_resolver.registration_count == 1
    assert evolution.release_registry.release_write_count == 0


def test_forged_rollback_plan_cannot_mutate_active_version() -> None:
    fixture = authorized_release_fixture()
    published = fixture.registry.publish_release(fixture.release)
    writes_before = fixture.registry.active_version_write_count
    forged = replace(
        published.rollback_plan,
        triggers=("caller_request_without_matching_plan",),
    )

    with pytest.raises(HarnessValidationError):
        fixture.registry.rollback(forged)

    assert fixture.registry.get_active_version("reader.repair") == published.version
    assert fixture.registry.active_version_write_count == writes_before


@pytest.mark.parametrize(
    "output",
    (
        {"promotion_observation": {"status": "approved"}},
        {"release_observation": {"version": "9.9.9"}},
        {"active_version_observation": "9.9.9"},
    ),
)
def test_ordinary_harness_run_observations_cannot_publish_skill(output) -> None:
    evolution = FakeSkillEvolutionPort()
    workflow = HarnessWorkflowSpec(
        workflow_id="ordinary-run-no-skill-release-handler",
        steps=(
            HarnessStepSpec(
                step_id="observe",
                worker_type=HarnessWorkerType.SKILL_EVOLUTION,
                output_key="candidate",
            ),
        ),
        entry_step_id="observe",
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "observe": lambda task: HarnessWorkerResult(
                status="succeeded",
                output=output,
            )
        },
    ).run(
        HarnessRunSpec(
            run_id="run-ordinary-no-skill-release",
            workflow=workflow,
            budget=HarnessBudget(
                max_turns=5,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=2,
                max_evolution_epochs=1,
                max_candidates_per_run=1,
                max_patch_operations=1,
                max_eval_cases=1,
                max_sandbox_runs=1,
            ),
        )
    )

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert evolution.releases == {}
    assert evolution.release_registry.version_history == {}
    assert evolution.active_versions == {}
    assert evolution.release_registry.release_write_count == 0


@pytest.mark.parametrize(
    "worker_fields",
    (
        {"output": {"promote": True}},
        {"output": {"nested": {"release": True}}},
        {"diagnostics": {"active_skill": "reader.repair@9.9.9"}},
        {"metrics": {"production_version": "9.9.9"}},
    ),
)
def test_ordinary_worker_promotion_aliases_fail_with_zero_release_writes(
    worker_fields,
) -> None:
    evolution = FakeSkillEvolutionPort()

    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(status="succeeded", **worker_fields)

    assert captured.value.code == "worker_decision_field_rejected"
    assert evolution.release_registry.release_write_count == 0
    assert evolution.release_registry.history_write_count == 0
    assert evolution.release_registry.active_version_write_count == 0
    assert evolution.releases == {}
    assert evolution.active_versions == {}


def test_unregistered_authority_ref_fails_before_any_write() -> None:
    fixture = authorized_release_fixture()
    unregistered = replace(
        fixture.release,
        release_authorization_ref=checksum_for({"authority": "not-registered"}),
        rollback_plan=replace(
            fixture.release.rollback_plan,
            release_authorization_ref=checksum_for({"authority": "not-registered"}),
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        fixture.registry.publish_release(unregistered)

    assert captured.value.code == "skill_release_authority_missing"
    _assert_zero_release_writes(fixture)


def test_resolver_refuses_non_held_out_evaluation_registration() -> None:
    fixture = authorized_release_fixture()
    canonical = fixture.resolver.resolve(fixture.authority.authorization_ref)
    resolver = InMemorySkillReleaseAuthorityResolver(fixture.side_effect_store)
    non_held_out = replace(
        canonical.evaluation,
        held_out_score=None,
        case_results=({"case_id": "train", "split": "train", "passed": True},),
    )

    with pytest.raises(HarnessValidationError) as captured:
        resolver.register(
            candidate=canonical.candidate,
            evaluation=non_held_out,
            promotion_decision=canonical.promotion_decision,
            release=canonical.release,
            side_effect_intent=canonical.side_effect_intent,
            side_effect_decision_ref=canonical.side_effect_decision.checksum,
        )

    assert captured.value.code == "skill_release_held_out_eval_missing"
    assert resolver.registration_count == 0


def test_resolver_refuses_failed_promotion_gate_registration() -> None:
    fixture = authorized_release_fixture()
    canonical = fixture.resolver.resolve(fixture.authority.authorization_ref)
    resolver = InMemorySkillReleaseAuthorityResolver(fixture.side_effect_store)
    failed_gate = replace(
        canonical.promotion_decision,
        gate_results=({"gate": "skill_promotion", "passed": False},),
    )

    with pytest.raises(HarnessValidationError) as captured:
        resolver.register(
            candidate=canonical.candidate,
            evaluation=canonical.evaluation,
            promotion_decision=failed_gate,
            release=canonical.release,
            side_effect_intent=canonical.side_effect_intent,
            side_effect_decision_ref=canonical.side_effect_decision.checksum,
        )

    assert captured.value.code == "skill_release_promotion_gate_failed"
    assert resolver.registration_count == 0


def _assert_zero_release_writes(fixture: AuthorizedReleaseFixture) -> None:
    assert fixture.registry.releases == {}
    assert fixture.registry.version_history == {}
    assert fixture.registry.active_versions == {}
    assert fixture.registry.release_write_count == 0
    assert fixture.registry.history_write_count == 0
    assert fixture.registry.active_version_write_count == 0
