from __future__ import annotations

import pytest

from framework.harness import (
    ContextAggregateGateResult,
    ContextAggregateVerificationResult,
    ContextAggregateVerifier,
    ContextCompactionActionExecutor,
    ContextCompactionActionType,
    ContextCompactionOutcome,
    ContextCompactionPlanner,
    ContextCompactionPlanningRequest,
    ContextCompactionPlanningStatus,
    ContextCompactionPolicy,
    ContextGroup,
    ContextGroupKind,
    ContextGroupMaterializer,
    ContextMaterializationRequest,
    ContextPhysicalAdmissionEvidence,
    ContextPhysicalMaterialization,
    ContextReconstructionPolicy,
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
    FakeArtifactPort,
    HarnessValidationError,
)
from framework.llm.context.harness_adapter import (
    Change1ContextPhysicalAdmissionVerifier,
)
from framework.llm.context.normalization import (
    CanonicalLLMRequestNormalizer,
    LLMRequestNormalizerRegistry,
)
from framework.llm.context.preflight import LLMRequestPreparer
from framework.llm.context.profile import ModelContextProfile
from framework.llm.context.tokens import LLMTokenCount, LLMTokenCounterRegistry
from framework.llm.models import LLMRequest


def _policy() -> ContextCompactionPolicy:
    return ContextCompactionPolicy(
        policy_revision="policy-verify-v1",
        action_order=(ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,),
        max_actions=2,
        max_summary_calls=0,
        max_replans=1,
        max_llm_calls=0,
        max_input_tokens=30,
        max_cost_usd=0.0,
        max_turns=2,
        keep_recent_complete_turns=1,
    )


def _source(policy: ContextCompactionPolicy):
    base = ContextGroupMaterializer().materialize(
        ContextMaterializationRequest(
            run_id="run-verify-1",
            task_binding_ref="task://verify",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-verify-v1",
            messages=(
                {"role": "user", "content_ref": "message://u"},
                {"role": "assistant", "content_ref": "message://a"},
            ),
        )
    )
    reconstructable = ContextGroup(
        group_kind=ContextGroupKind.RECONSTRUCTABLE,
        members=base.groups[:1][0].members,
        source_refs=("source://reconstructable",),
        reconstruction_policy=ContextReconstructionPolicy.DURABLE_REF,
        reconstruction_ref="artifact://reconstructable/1#sha256=abc",
    )
    return ContextSemanticSnapshot(
        run_id=base.run_id,
        task_binding_ref=base.task_binding_ref,
        groups=(*base.groups, reconstructable),
        policy_revision=base.policy_revision,
        physical_profile_revision=base.physical_profile_revision,
        snapshot_kind=ContextSemanticSnapshotKind.SOURCE,
    )


def _evidence(snapshot, *, admitted: bool, status: str = "admitted"):
    counts = {group.group_id: 10 for group in snapshot.groups}
    return ContextPhysicalAdmissionEvidence(
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_checksum=snapshot.checksum,
        prepared_fingerprint="sha256:prepared-verify-v1",
        physical_profile_revision=snapshot.physical_profile_revision,
        tokenizer_revision="tokenizer-verify-v1",
        normalizer_revision="normalizer-verify-v1",
        materialization_revision="materialization-verify-v1",
        admission_status="admitted" if admitted else status,
        admitted=admitted,
        input_tokens=10 + sum(counts.values()),
        max_input_tokens=30,
        fixed_input_tokens=10,
        group_input_tokens=counts,
    )


def _executed_result():
    policy = _policy()
    source = _source(policy)
    initial = _evidence(source, admitted=False, status="input_limit_exceeded")
    planned = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=source,
            initial_admission=initial,
            policy=policy,
        )
    )
    assert planned.status is ContextCompactionPlanningStatus.PLAN_READY
    execution = ContextCompactionActionExecutor(FakeArtifactPort()).execute(
        planned.plan,
        source_snapshot=source,
        initial_admission=initial,
        policy=policy,
    )
    assert execution.result_snapshot is not None
    return policy, source, initial, planned.plan, execution


def test_all_versioned_gates_bind_same_snapshots_and_admitted_physical_evidence() -> None:
    policy, source, _, plan, execution = _executed_result()
    aggregate = ContextAggregateVerifier().verify(
        source_snapshot=source,
        result_snapshot=execution.result_snapshot,
        plan=plan,
        policy=policy,
        action_results=execution.action_results,
        usage=execution.usage,
        physical_admission=_evidence(execution.result_snapshot, admitted=True),
    )

    assert aggregate.passed is True
    assert aggregate.outcome is ContextCompactionOutcome.VERIFIED
    assert aggregate.dispatch_authorized is True
    assert [gate.gate_name for gate in aggregate.gates] == list(
        ContextAggregateVerifier.REQUIRED_GATES
    )
    assert {
        (gate.input_ref, gate.result_ref) for gate in aggregate.gates
    } == {(source.checksum, execution.result_snapshot.checksum)}


def test_failed_prepared_physical_admission_overrides_legacy_estimate() -> None:
    policy, source, _, plan, execution = _executed_result()
    aggregate = ContextAggregateVerifier().verify(
        source_snapshot=source,
        result_snapshot=execution.result_snapshot,
        plan=plan,
        policy=policy,
        action_results=execution.action_results,
        usage=execution.usage,
        physical_admission=_evidence(
            execution.result_snapshot,
            admitted=False,
            status="input_limit_exceeded",
        ),
    )

    physical = next(
        gate
        for gate in aggregate.gates
        if gate.gate_name == "context_physical_admission@1"
    )
    assert aggregate.passed is False
    assert aggregate.outcome is ContextCompactionOutcome.POST_COMPACTION_VERIFY_FAILED
    assert aggregate.dispatch_authorized is False
    assert physical.passed is False


def test_aggregate_rejects_legacy_boolean_only_gate_evidence() -> None:
    gate = ContextAggregateGateResult(
        gate_name="context_structure@1",
        passed=True,
        input_ref="sha256:source",
        result_ref="sha256:result",
        reason_code="ok",
    )
    with pytest.raises(HarnessValidationError, match="requires versioned gate results"):
        ContextAggregateVerificationResult(
            source_snapshot_id="source",
            source_snapshot_checksum="sha256:source",
            result_snapshot_id="result",
            result_snapshot_checksum="sha256:result",
            physical_admission_evidence_id="admission",
            gates=(),
            passed=True,
            outcome=ContextCompactionOutcome.VERIFIED,
            reason_code="bad",
        )
    with pytest.raises(HarnessValidationError, match="same source/result"):
        ContextAggregateVerificationResult(
            source_snapshot_id="source",
            source_snapshot_checksum="sha256:source",
            result_snapshot_id="result",
            result_snapshot_checksum="sha256:result",
            physical_admission_evidence_id="admission",
            gates=(
                gate,
                ContextAggregateGateResult(
                    gate_name="context_protection@1",
                    passed=True,
                    input_ref="sha256:other",
                    result_ref="sha256:result",
                    reason_code="bad",
                ),
            ),
            passed=True,
            outcome=ContextCompactionOutcome.VERIFIED,
            reason_code="bad",
        )


class _FixedCounter:
    def count(self, payload, *, profile, normalizer_revision):
        return LLMTokenCount(
            message_tokens=20,
            tool_tokens=0,
            response_schema_tokens=0,
            media_tokens=0,
            protocol_overhead_tokens=0,
            total_input_tokens=20,
            method="exact",
            tokenizer_family=profile.tokenizer_family,
            tokenizer_revision=profile.tokenizer_revision,
            normalizer_revision=normalizer_revision,
        )


def test_change1_adapter_returns_exact_prepared_admission_evidence() -> None:
    policy = _policy()
    source = _source(policy)
    result = ContextSemanticSnapshot(
        run_id=source.run_id,
        task_binding_ref=source.task_binding_ref,
        groups=(source.groups[0],),
        policy_revision=source.policy_revision,
        physical_profile_revision="profile-change1-v1",
        snapshot_kind=ContextSemanticSnapshotKind.RESULT,
        parent_snapshot_id=source.snapshot_id,
    )
    profile = ModelContextProfile(
        provider="test",
        model="model-change1",
        deployment_id="deployment-change1",
        physical_context_window_tokens=100,
        max_output_tokens=50,
        default_output_tokens=10,
        tokenizer_family="tokenizer-change1",
        tokenizer_revision="tokenizer-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision="profile-change1-v1",
        operational_input_fraction=1.0,
        safety_margin_tokens=10,
        allow_conservative_fallback=False,
    )
    normalizers = LLMRequestNormalizerRegistry()
    normalizers.register(
        provider="test",
        revision="canonical-request-v1",
        normalizer=CanonicalLLMRequestNormalizer(),
    )
    counters = LLMTokenCounterRegistry()
    counters.register(
        tokenizer_family="tokenizer-change1",
        tokenizer_revision="tokenizer-v1",
        counter=_FixedCounter(),
    )
    adapter = Change1ContextPhysicalAdmissionVerifier(
        LLMRequestPreparer(normalizers=normalizers, token_counters=counters),
        lambda deployment_id, profile_revision: profile,
    )
    evidence = adapter.admit(
        ContextPhysicalMaterialization(
            result_snapshot=result,
            deployment_id="deployment-change1",
            profile_revision="profile-change1-v1",
            materialization_revision="result-materialization-v1",
            request=LLMRequest(messages=[{"role": "user", "content": "hello"}]),
            fixed_input_tokens=10,
            group_input_tokens={result.groups[0].group_id: 10},
        )
    )

    assert evidence.admitted is True
    assert evidence.input_tokens == 20
    assert evidence.physical_profile_revision == "profile-change1-v1"
    assert evidence.tokenizer_revision == "tokenizer-v1"
    assert evidence.prepared_fingerprint.startswith("sha256:")
