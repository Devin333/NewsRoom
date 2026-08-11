from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness import (
    ContextCompactionAction,
    ContextCompactionActionResult,
    ContextCompactionActionType,
    ContextCompactionOutcome,
    ContextCompactionPlan,
    ContextCompactionPolicy,
    ContextCompressionRecordV2,
    ContextGroup,
    ContextGroupKind,
    ContextGroupMember,
    ContextGroupMemberKind,
    ContextLossReport,
    ContextLossRisk,
    ContextProtectionReason,
    ContextReconstructionPolicy,
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
    ContextSummaryCandidate,
    ContextSummaryClaim,
    ContextToolTransactionState,
    HarnessValidationError,
)


def _member(
    ref: str = "message://1",
    *,
    ordinal: int = 0,
    kind: ContextGroupMemberKind = ContextGroupMemberKind.MESSAGE,
    role: str | None = "user",
    tool_call_id: str | None = None,
    semantic_metadata: dict | None = None,
    diagnostic_metadata: dict | None = None,
) -> ContextGroupMember:
    return ContextGroupMember(
        member_kind=kind,
        content_ref=ref,
        ordinal=ordinal,
        role=role,
        tool_call_id=tool_call_id,
        source_refs=("source://1",),
        semantic_metadata=semantic_metadata or {},
        diagnostic_metadata=diagnostic_metadata or {},
    )


def _group(
    *,
    kind: ContextGroupKind = ContextGroupKind.CONVERSATION_TURN,
    diagnostic_metadata: dict | None = None,
    semantic_metadata: dict | None = None,
) -> ContextGroup:
    return ContextGroup(
        group_kind=kind,
        members=(_member(),),
        source_refs=("source://1",),
        semantic_metadata=semantic_metadata or {},
        diagnostic_metadata=diagnostic_metadata or {},
    )


def _policy() -> ContextCompactionPolicy:
    return ContextCompactionPolicy(
        policy_revision="policy-v1",
        action_order=(
            ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,
            ContextCompactionActionType.SELECT_EVIDENCE_SPANS,
            ContextCompactionActionType.SUMMARIZE_GROUPS,
        ),
        max_actions=4,
        max_summary_calls=1,
        max_replans=1,
        max_llm_calls=1,
        max_input_tokens=1000,
        max_cost_usd=0.2,
        max_turns=2,
        protected_group_kinds=(ContextGroupKind.CURRENT_TASK,),
        protected_reasons=(ContextProtectionReason.CURRENT_TASK,),
    )


def test_group_identity_excludes_diagnostic_metadata_but_includes_semantics() -> None:
    first = _group(diagnostic_metadata={"trace_id": "trace-a"})
    diagnostic_change = _group(diagnostic_metadata={"trace_id": "trace-b"})
    semantic_change = _group(semantic_metadata={"required": True})

    assert first.group_id == diagnostic_change.group_id
    assert first.identity_checksum == diagnostic_change.identity_checksum
    assert first.group_id != semantic_change.group_id
    assert first.to_dict()["diagnostic_metadata"] == {"trace_id": "trace-a"}


def test_group_round_trip_is_strict_and_detects_identity_tampering() -> None:
    group = _group()
    payload = group.to_dict()

    assert ContextGroup.from_dict(payload) == group
    with pytest.raises(HarnessValidationError, match="unsupported fields"):
        ContextGroup.from_dict({**payload, "verified": True})
    with pytest.raises(HarnessValidationError, match="group_id"):
        ContextGroup.from_dict({**payload, "group_id": "context-group://tampered"})


def test_completed_tool_transaction_requires_matching_call_and_result() -> None:
    call = _member(
        "tool-call://1",
        kind=ContextGroupMemberKind.TOOL_CALL,
        role="assistant",
        tool_call_id="call-1",
    )
    result = _member(
        "tool-result://1",
        ordinal=1,
        kind=ContextGroupMemberKind.TOOL_RESULT,
        role="tool",
        tool_call_id="call-1",
    )

    transaction = ContextGroup(
        group_kind=ContextGroupKind.TOOL_TRANSACTION,
        members=(call, result),
        source_refs=("tool-run://1",),
        tool_transaction_state=ContextToolTransactionState.COMPLETED,
    )

    assert transaction.tool_transaction_state is ContextToolTransactionState.COMPLETED
    with pytest.raises(HarnessValidationError, match="at least one tool result"):
        ContextGroup(
            group_kind=ContextGroupKind.TOOL_TRANSACTION,
            members=(call,),
            source_refs=("tool-run://1",),
            tool_transaction_state=ContextToolTransactionState.COMPLETED,
        )
    with pytest.raises(HarnessValidationError, match="must match"):
        ContextGroup(
            group_kind=ContextGroupKind.TOOL_TRANSACTION,
            members=(
                call,
                _member(
                    "tool-result://1",
                    ordinal=1,
                    kind=ContextGroupMemberKind.TOOL_RESULT,
                    role="tool",
                    tool_call_id="other",
                ),
            ),
            source_refs=("tool-run://1",),
            tool_transaction_state=ContextToolTransactionState.COMPLETED,
        )


def test_pending_tool_transaction_must_be_protected() -> None:
    call = _member(
        "tool-call://1",
        kind=ContextGroupMemberKind.TOOL_CALL,
        role="assistant",
        tool_call_id="call-1",
    )

    with pytest.raises(HarnessValidationError, match="must be protected"):
        ContextGroup(
            group_kind=ContextGroupKind.TOOL_TRANSACTION,
            members=(call,),
            source_refs=("tool-run://1",),
            tool_transaction_state=ContextToolTransactionState.PENDING,
        )


def test_reconstructable_group_requires_real_ref_policy_pair() -> None:
    with pytest.raises(HarnessValidationError, match="requires reconstruction_ref"):
        ContextGroup(
            group_kind=ContextGroupKind.RECONSTRUCTABLE,
            members=(_member(),),
            source_refs=("source://1",),
            reconstruction_policy=ContextReconstructionPolicy.DURABLE_REF,
        )


def test_compaction_policy_round_trip_and_bounds() -> None:
    policy = _policy()

    assert ContextCompactionPolicy.from_dict(policy.to_dict()) == policy
    with pytest.raises(HarnessValidationError, match="unsupported compaction action"):
        ContextCompactionPolicy.from_dict(
            {**policy.to_dict(), "action_order": ["truncate_string"]}
        )
    with pytest.raises(HarnessValidationError, match="max_actions"):
        ContextCompactionPolicy.from_dict({**policy.to_dict(), "max_actions": 0})
    with pytest.raises(TypeError):
        policy.metadata["mutate"] = True  # type: ignore[index]


def test_plan_identity_binds_source_policy_profile_and_actions() -> None:
    action = ContextCompactionAction(
        action_type=ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,
        target_group_ids=("context-group://one",),
    )
    plan = ContextCompactionPlan(
        source_snapshot_id="context-snapshot-v2://source",
        source_snapshot_checksum="sha256:" + "a" * 64,
        task_binding_ref="task://current",
        target_input_tokens=100,
        max_actions=2,
        max_summary_calls=0,
        max_replans=1,
        actions=(action,),
        protected_group_ids=("context-group://protected",),
        policy_revision="policy-v1",
        physical_profile_revision="profile-v1",
        initial_admission_ref="context-physical-admission://one",
        max_llm_calls=1,
        max_cost_usd=0.2,
        max_turns=2,
    )

    assert ContextCompactionPlan.from_dict(plan.to_dict()) == plan
    assert replace(plan, physical_profile_revision="profile-v2", plan_id=None, identity_checksum=None).plan_id != plan.plan_id


def test_plan_rejects_summary_action_above_summary_budget() -> None:
    action = ContextCompactionAction(
        action_type=ContextCompactionActionType.SUMMARIZE_GROUPS,
        target_group_ids=("context-group://one",),
    )

    with pytest.raises(HarnessValidationError, match="summary actions"):
        ContextCompactionPlan(
            source_snapshot_id="context-snapshot-v2://source",
            source_snapshot_checksum="sha256:" + "a" * 64,
            task_binding_ref="task://current",
            target_input_tokens=100,
            max_actions=2,
            max_summary_calls=0,
            max_replans=1,
            actions=(action,),
            protected_group_ids=(),
            policy_revision="policy-v1",
            physical_profile_revision="profile-v1",
            initial_admission_ref="context-physical-admission://one",
            max_llm_calls=1,
            max_cost_usd=0.2,
            max_turns=2,
        )


def test_summary_candidate_requires_supported_claims_and_rejects_authority() -> None:
    claim = ContextSummaryClaim(supporting_refs=("source://1",))
    candidate = ContextSummaryCandidate(
        summary_artifact_ref="artifact://summary/1#sha256=abc",
        covered_group_ids=("context-group://one",),
        source_refs=("source://1",),
        claims=(claim,),
        omitted_topics=("non-required detail",),
        unresolved_questions=("open question",),
        tool_outcome_refs=(),
        loss_risk=ContextLossRisk.LOW,
        worker_id="summary-worker",
        model_id="model-a",
        worker_revision="worker-v1",
        model_revision="model-v1",
    )

    assert ContextSummaryCandidate.from_dict(candidate.to_dict()) == candidate
    with pytest.raises(HarnessValidationError, match="unsupported fields"):
        ContextSummaryCandidate.from_dict({**candidate.to_dict(), "verified": True})
    with pytest.raises(HarnessValidationError, match="supporting_refs"):
        ContextSummaryClaim(supporting_refs=())


def test_semantic_snapshot_identity_is_immutable_and_round_trips() -> None:
    snapshot = ContextSemanticSnapshot(
        run_id="run-1",
        step_id="step-1",
        task_binding_ref="task://current",
        groups=(_group(),),
        policy_revision="policy-v1",
        physical_profile_revision="profile-v1",
        snapshot_kind=ContextSemanticSnapshotKind.SOURCE,
    )

    assert ContextSemanticSnapshot.from_dict(snapshot.to_dict()) == snapshot
    with pytest.raises(HarnessValidationError, match="checksum"):
        ContextSemanticSnapshot.from_dict({**snapshot.to_dict(), "checksum": "sha256:bad"})


def test_v2_record_round_trip_binds_snapshots_actions_and_gates() -> None:
    group = _group()
    source = ContextSemanticSnapshot(
        run_id="run-1",
        task_binding_ref="task://current",
        groups=(group,),
        policy_revision="policy-v1",
        snapshot_kind=ContextSemanticSnapshotKind.SOURCE,
    )
    result = ContextSemanticSnapshot(
        run_id="run-1",
        task_binding_ref="task://current",
        groups=(group,),
        policy_revision="policy-v1",
        snapshot_kind=ContextSemanticSnapshotKind.RESULT,
        parent_snapshot_id=source.snapshot_id,
    )
    action = ContextCompactionAction(
        action_type=ContextCompactionActionType.REPLACE_WITH_REFERENCE,
        target_group_ids=(group.group_id,),
    )
    action_result = ContextCompactionActionResult(
        action=action,
        source_snapshot_id=source.snapshot_id,
        result_group_ids=(group.group_id,),
        reconstruction_refs=("artifact://reconstruct/1#sha256=abc",),
    )
    record = ContextCompressionRecordV2(
        run_id="run-1",
        source_snapshot_id=source.snapshot_id,
        source_snapshot_checksum=source.checksum,
        result_snapshot_id=result.snapshot_id,
        result_snapshot_checksum=result.checksum,
        plan_id="context-plan://one",
        policy_revision="policy-v1",
        action_results=(action_result,),
        before_input_tokens=200,
        after_input_tokens=100,
        retained_group_ids=(group.group_id,),
        removed_group_ids=(),
        replaced_group_ids=(group.group_id,),
        protected_group_ids=(),
        reconstruction_refs=("artifact://reconstruct/1#sha256=abc",),
        source_refs=("source://1",),
        summary_refs=(),
        loss_report=ContextLossReport(replaced_group_ids=(group.group_id,)),
        gate_results=(
            {
                "gate": "context_physical_admission@1",
                "passed": True,
                "input_ref": result.checksum,
                "result_ref": "sha256:" + "b" * 64,
                "reason_code": "admitted",
            },
        ),
        aggregate_verdict=ContextCompactionOutcome.VERIFIED,
        reason_code="all_gates_passed",
        profile_revision="profile-v1",
        tokenizer_revision="tokenizer-v1",
        normalizer_revision="normalizer-v1",
    )

    assert ContextCompressionRecordV2.from_dict(record.to_dict()) == record
    with pytest.raises(HarnessValidationError, match="record checksum"):
        ContextCompressionRecordV2.from_dict({**record.to_dict(), "checksum": "sha256:bad"})
