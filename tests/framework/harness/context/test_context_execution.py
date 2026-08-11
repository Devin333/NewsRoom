from __future__ import annotations

from typing import Any

import pytest

from framework.harness import (
    ContextCompactionActionExecutor,
    ContextCompactionActionType,
    ContextCompactionPlanner,
    ContextCompactionPlanningRequest,
    ContextCompactionPlanningStatus,
    ContextCompactionPolicy,
    ContextCompactionExecutionStatus,
    ContextGroup,
    ContextGroupKind,
    ContextGroupMember,
    ContextGroupMemberKind,
    ContextGroupMaterializer,
    ContextMaterializationRequest,
    ContextPhysicalAdmissionEvidence,
    ContextReconstructionPolicy,
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
    ContextToolTransactionState,
    ContextProtectionReason,
    FakeArtifactPort,
    HarnessValidationError,
)


def _policy(action: ContextCompactionActionType) -> ContextCompactionPolicy:
    return ContextCompactionPolicy(
        policy_revision="policy-exec-v1",
        action_order=(action,),
        max_actions=3,
        max_summary_calls=1,
        max_replans=1,
        max_llm_calls=1,
        max_input_tokens=30,
        max_cost_usd=1.0,
        max_turns=3,
        keep_recent_complete_turns=1,
    )


def _snapshot(
    policy: ContextCompactionPolicy,
    *,
    messages: tuple[dict, ...] | None = None,
    evidence_items: tuple[dict, ...] = (),
    authorized_tools: tuple[dict, ...] = (),
    extra_groups: tuple[ContextGroup, ...] = (),
) -> ContextSemanticSnapshot:
    snapshot = ContextGroupMaterializer().materialize(
        ContextMaterializationRequest(
            run_id="run-exec-1",
            step_id="step-1",
            task_binding_ref="task://current",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-exec-v1",
            messages=messages
            or (
                {"role": "user", "content_ref": "message://u-1"},
                {"role": "assistant", "content_ref": "message://a-1"},
            ),
            evidence_items=evidence_items,
            authorized_tools=authorized_tools,
        )
    )
    if not extra_groups:
        return snapshot
    return ContextSemanticSnapshot(
        run_id=snapshot.run_id,
        step_id=snapshot.step_id,
        task_binding_ref=snapshot.task_binding_ref,
        groups=(*snapshot.groups, *extra_groups),
        policy_revision=snapshot.policy_revision,
        physical_profile_revision=snapshot.physical_profile_revision,
        snapshot_kind=ContextSemanticSnapshotKind.SOURCE,
    )


def _admission(snapshot: ContextSemanticSnapshot) -> ContextPhysicalAdmissionEvidence:
    counts = {group.group_id: 10 for group in snapshot.groups}
    return ContextPhysicalAdmissionEvidence(
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_checksum=snapshot.checksum,
        prepared_fingerprint="sha256:prepared-exec-v1",
        physical_profile_revision=snapshot.physical_profile_revision,
        tokenizer_revision="tokenizer-exec-v1",
        normalizer_revision="normalizer-exec-v1",
        materialization_revision="materialization-exec-v1",
        admission_status="input_limit_exceeded",
        admitted=False,
        input_tokens=10 + sum(counts.values()),
        max_input_tokens=30,
        fixed_input_tokens=10,
        group_input_tokens=counts,
    )


def _reference_group(
    *,
    kind: ContextGroupKind = ContextGroupKind.RECONSTRUCTABLE,
    ref: str = "artifact://source/1#sha256=source",
) -> ContextGroup:
    member = ContextGroupMember(
        member_kind=ContextGroupMemberKind.REFERENCE,
        content_ref=ref,
        ordinal=0,
        source_refs=("source://1",),
    )
    return ContextGroup(
        group_kind=kind,
        members=(member,),
        source_refs=("source://1",),
        reconstruction_policy=ContextReconstructionPolicy.DURABLE_REF,
        reconstruction_ref=ref,
    )


def _plan(
    snapshot: ContextSemanticSnapshot,
    policy: ContextCompactionPolicy,
    admission: ContextPhysicalAdmissionEvidence,
):
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=admission,
            policy=policy,
        )
    )
    assert result.status is ContextCompactionPlanningStatus.PLAN_READY
    assert result.plan is not None
    return result.plan


def test_drop_removes_complete_group_and_leaves_source_snapshot_unchanged() -> None:
    policy = _policy(ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP)
    source = _snapshot(policy, extra_groups=(_reference_group(),))
    plan = _plan(source, policy, _admission(source))
    executor = ContextCompactionActionExecutor(FakeArtifactPort())

    result = executor.execute(
        plan,
        source_snapshot=source,
        initial_admission=_admission(source),
        policy=policy,
    )

    assert result.status is ContextCompactionExecutionStatus.APPLIED
    assert result.result_snapshot is not None
    assert result.result_snapshot.parent_snapshot_id == source.snapshot_id
    assert len(result.result_snapshot.groups) == len(source.groups) - 1
    assert source.groups[-1].group_kind is ContextGroupKind.RECONSTRUCTABLE
    assert result.action_results[0].loss_report.loss_risk.value == "none"
    assert result.reconstruction_refs == ("artifact://source/1#sha256=source",)


def test_replace_uses_injected_artifact_port_and_checksum_bound_ref() -> None:
    policy = _policy(ContextCompactionActionType.REPLACE_WITH_REFERENCE)
    source = _snapshot(
        policy,
        extra_groups=(
            _reference_group(kind=ContextGroupKind.MEMORY_REFERENCE),
        ),
    )
    artifact_port = FakeArtifactPort()
    result = ContextCompactionActionExecutor(artifact_port).execute(
        _plan(source, policy, _admission(source)),
        source_snapshot=source,
        initial_admission=_admission(source),
        policy=policy,
    )
    replacement = result.result_snapshot.groups[-1]

    assert result.status is ContextCompactionExecutionStatus.APPLIED
    assert replacement.group_kind is ContextGroupKind.MEMORY_REFERENCE
    assert replacement.group_id != source.groups[-1].group_id
    assert replacement.reconstruction_ref in result.reconstruction_refs
    assert "#sha256=" in replacement.reconstruction_ref
    assert len(artifact_port.storage) == 1
    assert artifact_port.storage[next(iter(artifact_port.storage))]["artifact_type"] == (
        "context-reconstruction-reference"
    )


def test_reduce_authorized_tool_set_removes_only_unreachable_schema() -> None:
    policy = _policy(ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET)
    source = _snapshot(
        policy,
        authorized_tools=(
            {
                "tool_id": "search",
                "schema_ref": "schema://search-v1",
                "authorization_ref": "authorization://search",
                "reachable": False,
            },
        ),
    )
    result = ContextCompactionActionExecutor(FakeArtifactPort()).execute(
        _plan(source, policy, _admission(source)),
        source_snapshot=source,
        initial_admission=_admission(source),
        policy=policy,
    )

    assert result.status is ContextCompactionExecutionStatus.APPLIED
    assert not any(
        group.group_kind is ContextGroupKind.AUTHORIZED_TOOL_SCHEMA
        for group in result.result_snapshot.groups
    )
    assert ContextProtectionReason.PENDING_TOOL_TRANSACTION not in set(
        result.result_snapshot.groups[0].protection_reasons
    )


def test_evidence_selection_preserves_required_and_conflict_refs() -> None:
    policy = _policy(ContextCompactionActionType.SELECT_EVIDENCE_SPANS)
    source = _snapshot(
        policy,
        evidence_items=(
            {
                "evidence_id": "evidence-exec-1",
                "source_refs": ("source://paper",),
                "span_refs": ("span://1", "span://2", "span://3"),
                "lineage_refs": ("lineage://1",),
                "required_span_refs": ("span://1",),
                "selected_span_refs": ("span://1", "span://2"),
                "required_citation_refs": ("citation://1",),
                "conflict_refs": ("conflict://1",),
            },
        ),
    )
    result = ContextCompactionActionExecutor(FakeArtifactPort()).execute(
        _plan(source, policy, _admission(source)),
        source_snapshot=source,
        initial_admission=_admission(source),
        policy=policy,
    )
    evidence = next(
        group
        for group in result.result_snapshot.groups
        if group.group_kind is ContextGroupKind.EVIDENCE
    )

    assert [member.content_ref for member in evidence.members] == [
        "span://1",
        "span://2",
    ]
    assert evidence.required_citation_refs == ("citation://1",)
    assert evidence.semantic_metadata["conflict_refs"] == ("conflict://1",)
    assert result.action_results[0].loss_report.omitted_span_refs == ("span://3",)


def test_old_conversation_compaction_preserves_recent_complete_tail() -> None:
    policy = _policy(ContextCompactionActionType.COMPACT_OLD_CONVERSATION)
    source = _snapshot(
        policy,
        messages=(
            {"role": "user", "content_ref": "message://u-1"},
            {"role": "assistant", "content_ref": "message://a-1"},
            {"role": "user", "content_ref": "message://u-2"},
            {"role": "assistant", "content_ref": "message://a-2"},
        ),
    )
    result = ContextCompactionActionExecutor(FakeArtifactPort()).execute(
        _plan(source, policy, _admission(source)),
        source_snapshot=source,
        initial_admission=_admission(source),
        policy=policy,
    )
    refs = {
        member.content_ref
        for group in result.result_snapshot.groups
        for member in group.members
    }

    assert "message://u-1" not in refs
    assert "message://a-1" not in refs
    assert "message://u-2" in refs
    assert "message://a-2" in refs


def test_summary_action_is_rejected_without_a_summary_worker_and_never_promotes() -> None:
    policy = _policy(ContextCompactionActionType.SUMMARIZE_GROUPS)
    source = _snapshot(
        policy,
        messages=(
            {"role": "user", "content_ref": "message://u-1"},
            {"role": "assistant", "content_ref": "message://a-1"},
            {"role": "user", "content_ref": "message://u-2"},
            {"role": "assistant", "content_ref": "message://a-2"},
        ),
    )
    result = ContextCompactionActionExecutor(FakeArtifactPort()).execute(
        _plan(source, policy, _admission(source)),
        source_snapshot=source,
        initial_admission=_admission(source),
        policy=policy,
    )

    assert result.status is ContextCompactionExecutionStatus.SUMMARY_REJECTED
    assert result.outcome.value == "summary_rejected"
    assert result.result_snapshot is None
    assert result.summary_refs == ()


class _InvalidArtifactPort:
    def write_artifact(self, request: Any) -> dict[str, Any]:
        return {"ref": "fabricated"}

    def read_artifact(self, ref: str) -> dict[str, Any]:
        return {}


def test_replace_rejects_artifact_ports_that_do_not_return_real_refs() -> None:
    policy = _policy(ContextCompactionActionType.REPLACE_WITH_REFERENCE)
    source = _snapshot(
        policy,
        extra_groups=(_reference_group(kind=ContextGroupKind.MEMORY_REFERENCE),),
    )
    with pytest.raises(HarnessValidationError, match="ArtifactRef"):
        ContextCompactionActionExecutor(_InvalidArtifactPort()).execute(
            _plan(source, policy, _admission(source)),
            source_snapshot=source,
            initial_admission=_admission(source),
            policy=policy,
        )
