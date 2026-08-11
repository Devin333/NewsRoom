from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness import (
    ContextCompactionAction,
    ContextCompactionActionDefinition,
    ContextCompactionActionRegistry,
    ContextCompactionActionType,
    ContextCompactionPlanner,
    ContextCompactionPlanningRequest,
    ContextCompactionPlanningStatus,
    ContextCompactionPolicy,
    ContextCompactionPolicyResolver,
    ContextGroup,
    ContextGroupKind,
    ContextGroupMember,
    ContextGroupMemberKind,
    ContextGroupMaterializer,
    ContextMaterializationRequest,
    ContextPhysicalAdmissionEvidence,
    ContextPlanningBudgetUsage,
    ContextProtectionReason,
    ContextReconstructionPolicy,
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
    ContextToolTransactionState,
    HarnessValidationError,
)


def _policy(
    *,
    action_order: tuple[ContextCompactionActionType, ...] | None = None,
    max_actions: int = 6,
    max_summary_calls: int = 1,
    max_input_tokens: int = 30,
    keep_recent_complete_turns: int = 1,
) -> ContextCompactionPolicy:
    return ContextCompactionPolicy(
        policy_revision="policy-v1",
        action_order=action_order
        or (
            ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,
            ContextCompactionActionType.REPLACE_WITH_REFERENCE,
            ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET,
            ContextCompactionActionType.SELECT_EVIDENCE_SPANS,
            ContextCompactionActionType.COMPACT_OLD_CONVERSATION,
            ContextCompactionActionType.SUMMARIZE_GROUPS,
        ),
        max_actions=max_actions,
        max_summary_calls=max_summary_calls,
        max_replans=2,
        max_llm_calls=1,
        max_input_tokens=max_input_tokens,
        max_cost_usd=1.0,
        max_turns=3,
        keep_recent_complete_turns=keep_recent_complete_turns,
        protected_reasons=(ContextProtectionReason.CONTROL_DECISION,),
    )


def _snapshot(
    *,
    messages: tuple[dict, ...] | None = None,
    evidence_items: tuple[dict, ...] = (),
    authorized_tools: tuple[dict, ...] = (),
    extra_groups: tuple[ContextGroup, ...] = (),
    policy: ContextCompactionPolicy | None = None,
) -> ContextSemanticSnapshot:
    policy = policy or _policy()
    base = ContextGroupMaterializer().materialize(
        # The planner receives a fully resolved profile; materializer itself
        # remains independent of provider/tokenizer implementations.
        ContextMaterializationRequest(
            run_id="run-1",
            step_id="step-1",
            task_binding_ref="task://current",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-v1",
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
        return base
    return ContextSemanticSnapshot(
        run_id=base.run_id,
        step_id=base.step_id,
        task_binding_ref=base.task_binding_ref,
        groups=(*base.groups, *extra_groups),
        policy_revision=base.policy_revision,
        physical_profile_revision=base.physical_profile_revision,
        snapshot_kind=ContextSemanticSnapshotKind.SOURCE,
    )


def _admission(
    snapshot: ContextSemanticSnapshot,
    *,
    admitted: bool = False,
    input_tokens: int | None = None,
    max_input_tokens: int = 30,
    status: str = "input_limit_exceeded",
) -> ContextPhysicalAdmissionEvidence:
    counts = {group.group_id: 10 for group in snapshot.groups}
    fixed = 10
    total = fixed + sum(counts.values())
    if input_tokens is not None:
        raise AssertionError("test admission uses exact group counts")
    return ContextPhysicalAdmissionEvidence(
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_checksum=snapshot.checksum,
        prepared_fingerprint="sha256:prepared-v1",
        physical_profile_revision="profile-v1",
        tokenizer_revision="tokenizer-v1",
        normalizer_revision="normalizer-v1",
        materialization_revision="materialization-v1",
        admission_status="admitted" if admitted else status,
        admitted=admitted,
        input_tokens=total if not admitted else min(total, max_input_tokens),
        max_input_tokens=max_input_tokens,
        fixed_input_tokens=fixed if not admitted else max(0, min(fixed, max_input_tokens - sum(counts.values()))),
        group_input_tokens=counts,
    )


def _reconstructable_group() -> ContextGroup:
    member = ContextGroupMember(
        member_kind=ContextGroupMemberKind.REFERENCE,
        content_ref="artifact://reconstructable/1#sha256=abc",
        ordinal=0,
        source_refs=("source://reconstructable-1",),
    )
    return ContextGroup(
        group_kind=ContextGroupKind.RECONSTRUCTABLE,
        members=(member,),
        source_refs=("source://reconstructable-1",),
        reconstruction_policy=ContextReconstructionPolicy.DURABLE_REF,
        reconstruction_ref="artifact://reconstructable/1#sha256=abc",
    )


def test_planner_returns_stable_plan_and_reversible_action_first() -> None:
    policy = _policy()
    snapshot = _snapshot(policy=policy, extra_groups=(_reconstructable_group(),))
    admission = _admission(snapshot)
    request = ContextCompactionPlanningRequest(
        source_snapshot=snapshot,
        initial_admission=admission,
        policy=policy,
    )
    first = ContextCompactionPlanner().plan(request)
    second = ContextCompactionPlanner().plan(request)

    assert first.status is ContextCompactionPlanningStatus.PLAN_READY
    assert first.plan is not None
    assert first.plan.plan_id == second.plan.plan_id
    assert first.plan.actions[0].action_type is ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP
    assert all(
        action.action_type is not ContextCompactionActionType.SUMMARIZE_GROUPS
        for action in first.plan.actions[:1]
    )


def test_admitted_source_never_receives_a_compaction_plan() -> None:
    snapshot = _snapshot()
    admission = _admission(snapshot, admitted=True)
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=admission,
            policy=_policy(),
        )
    )

    assert result.status is ContextCompactionPlanningStatus.NO_COMPACTION_REQUIRED
    assert result.plan is None


def test_physical_admission_evidence_and_planning_result_round_trip_are_strict() -> None:
    snapshot = _snapshot()
    admission = _admission(snapshot)
    admission_round_trip = type(admission).from_dict(admission.to_dict())
    assert admission_round_trip == admission
    with pytest.raises(HarnessValidationError, match="checksum"):
        type(admission).from_dict({**admission.to_dict(), "checksum": "sha256:bad"})
    with pytest.raises(TypeError):
        admission.group_input_tokens[snapshot.groups[0].group_id] = 99  # type: ignore[index]

    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=admission,
            policy=_policy(),
        )
    )
    assert type(result).from_dict(result.to_dict()) == result


def test_protected_context_and_action_budget_are_typed_fail_closed_results() -> None:
    protected_policy = _policy(max_input_tokens=20)
    protected_snapshot = _snapshot(
        messages=({"role": "system", "content_ref": "policy://system"},),
        policy=protected_policy,
    )
    protected_admission = _admission(protected_snapshot, max_input_tokens=15)
    protected_result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=protected_snapshot,
            initial_admission=protected_admission,
            policy=protected_policy,
        )
    )
    exhausted_snapshot = _snapshot()
    exhausted_policy = _policy()
    exhausted_result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=exhausted_snapshot,
            initial_admission=_admission(exhausted_snapshot),
            policy=exhausted_policy,
            budget_usage=ContextPlanningBudgetUsage(actions=exhausted_policy.max_actions),
        )
    )

    assert protected_result.status is ContextCompactionPlanningStatus.PROTECTED_CONTEXT_EXCEEDS_WINDOW
    assert exhausted_result.status is ContextCompactionPlanningStatus.ACTION_BUDGET_EXHAUSTED


def test_non_compactable_physical_failure_has_no_plan() -> None:
    snapshot = _snapshot()
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=_admission(
                snapshot,
                status="normalizer_unavailable",
            ),
            policy=_policy(),
        )
    )

    assert result.status is ContextCompactionPlanningStatus.NO_ALLOWED_COMPACTION
    assert result.reason_code == "physical_admission_failure_is_not_compactable"


def test_evidence_selection_is_query_bound_and_retains_required_spans() -> None:
    policy = _policy(
        action_order=(ContextCompactionActionType.SELECT_EVIDENCE_SPANS,)
    )
    snapshot = _snapshot(
        policy=policy,
        evidence_items=(
            {
                "evidence_id": "evidence-1",
                "source_refs": ("source://paper-1",),
                "span_refs": ("span://1", "span://2", "span://3"),
                "lineage_refs": ("lineage://1",),
                "required_span_refs": ("span://1",),
                "selected_span_refs": ("span://1", "span://2"),
                "required_citation_refs": ("citation://1",),
            },
        ),
    )
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=_admission(snapshot),
            policy=policy,
        )
    )

    assert result.status is ContextCompactionPlanningStatus.PLAN_READY
    assert result.plan is not None
    action = result.plan.actions[0]
    assert action.action_type is ContextCompactionActionType.SELECT_EVIDENCE_SPANS
    assert action.parameters["required_span_refs"] == ("span://1",)
    assert action.parameters["required_citation_refs"] == ("citation://1",)


def test_pending_tool_transaction_blocks_tool_reduction() -> None:
    policy = _policy(action_order=(ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET,))
    snapshot = _snapshot(
        policy=policy,
        authorized_tools=(
            {
                "tool_id": "search",
                "schema_ref": "schema://search-v1",
                "authorization_ref": "authorization://search",
                "reachable": False,
            },
        ),
        messages=(
            {"role": "user", "content_ref": "message://u"},
            {
                "role": "assistant",
                "content_ref": "message://tool-request",
                "tool_calls": ({"id": "call-1", "name": "search"},),
            },
        ),
    )
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=_admission(snapshot),
            policy=policy,
        )
    )

    assert result.status is ContextCompactionPlanningStatus.NO_ALLOWED_COMPACTION


def test_recent_complete_tail_is_not_a_compaction_target() -> None:
    policy = _policy(
        action_order=(ContextCompactionActionType.COMPACT_OLD_CONVERSATION,),
        keep_recent_complete_turns=1,
    )
    messages: list[dict] = []
    for index in range(3):
        messages.extend(
            (
                {"role": "user", "content_ref": f"message://u-{index}"},
                {"role": "assistant", "content_ref": f"message://a-{index}"},
            )
        )
    snapshot = _snapshot(policy=policy, messages=tuple(messages))
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=_admission(snapshot),
            policy=policy,
        )
    )

    assert result.status is ContextCompactionPlanningStatus.PLAN_READY
    assert result.plan is not None
    target_refs = {
        member.content_ref
        for group in snapshot.groups
        if group.group_id in result.plan.actions[0].target_group_ids
        for member in group.members
    }
    assert "message://u-2" not in target_refs
    assert "message://a-2" not in target_refs
    assert "message://u-0" in target_refs


def test_policy_composition_rejects_unknown_actions_bad_order_and_child_expansion() -> None:
    registry = ContextCompactionActionRegistry.standard()
    resolver = ContextCompactionPolicyResolver(registry)
    payload = _policy().to_dict()
    with pytest.raises(HarnessValidationError, match="unsupported compaction action"):
        resolver.resolve({**payload, "action_order": ["truncate_string"]})
    with pytest.raises(HarnessValidationError, match="reversible"):
        resolver.resolve(
            {
                **payload,
                "action_order": [
                    ContextCompactionActionType.SUMMARIZE_GROUPS.value,
                    ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP.value,
                ],
            }
        )
    child = _policy(max_actions=100, max_input_tokens=1000).to_dict()
    effective = resolver.resolve(child, parent=_policy())

    assert effective.max_actions == _policy().max_actions
    assert effective.max_input_tokens == _policy().max_input_tokens
    assert effective.policy_revision != _policy().policy_revision


def test_plan_validator_rejects_stale_admission_and_partial_member_targets() -> None:
    policy = _policy(action_order=(ContextCompactionActionType.COMPACT_OLD_CONVERSATION,))
    snapshot = _snapshot(
        policy=policy,
        messages=(
            {"role": "user", "content_ref": "message://u-1"},
            {"role": "assistant", "content_ref": "message://a-1"},
            {"role": "user", "content_ref": "message://u-2"},
            {"role": "assistant", "content_ref": "message://a-2"},
        ),
    )
    admission = _admission(snapshot)
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=admission,
            policy=policy,
        )
    )
    assert result.plan is not None
    stale = replace(
        admission,
        prepared_fingerprint="sha256:other",
        evidence_id=None,
        checksum=None,
    )
    with pytest.raises(HarnessValidationError, match="admission evidence"):
        ContextCompactionPlanner()._validator.validate(  # type: ignore[attr-defined]
            result.plan,
            source_snapshot=snapshot,
            policy=policy,
            initial_admission=stale,
        )
    member_id = snapshot.groups[0].members[0].member_id
    action = ContextCompactionAction(
        action_type=ContextCompactionActionType.COMPACT_OLD_CONVERSATION,
        target_group_ids=(member_id,),
        parameters={
            "complete_turn_group_ids": (member_id,),
            "keep_recent_complete_turns": 1,
        },
    )
    with pytest.raises(HarnessValidationError, match="complete groups"):
        ContextCompactionPlanner()._validator.validate(  # type: ignore[attr-defined]
            replace(result.plan, actions=(action,), plan_id=None, identity_checksum=None),
            source_snapshot=snapshot,
            policy=policy,
            initial_admission=admission,
        )


def test_unregistered_action_cannot_be_composed() -> None:
    registry = ContextCompactionActionRegistry(
        (
            ContextCompactionActionDefinition(
                ContextCompactionActionType.COMPACT_OLD_CONVERSATION,
                frozenset({"complete_turn_group_ids", "keep_recent_complete_turns"}),
            ),
        )
    )
    policy = _policy(action_order=(ContextCompactionActionType.SUMMARIZE_GROUPS,))

    with pytest.raises(HarnessValidationError, match="unregistered"):
        ContextCompactionPolicyResolver(registry).resolve(policy.to_dict())
