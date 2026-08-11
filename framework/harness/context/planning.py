from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from framework.harness.context.compaction_models import (
    REVERSIBLE_CONTEXT_ACTIONS,
    ContextCompactionAction,
    ContextCompactionActionType,
    ContextCompactionPlan,
    ContextCompactionPolicy,
    ContextLossRisk,
)
from framework.harness.context.group_models import (
    ContextGroup,
    ContextGroupKind,
    ContextProtectionReason,
    ContextReconstructionPolicy,
    ContextToolTransactionState,
)
from framework.harness.context.planning_models import (
    ContextCompactionPlanningResult,
    ContextCompactionPlanningStatus,
    ContextPhysicalAdmissionEvidence,
    ContextPlanningBudgetUsage,
)
from framework.harness.context.verified_common import identity, required_text, text_tuple
from framework.harness.context.verified_records import (
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
)
from framework.harness.control_plane.errors import HarnessValidationError


@dataclass(frozen=True)
class ContextCompactionActionDefinition:
    action_type: ContextCompactionActionType | str
    parameter_fields: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "action_type",
            ContextCompactionActionType(self.action_type),
        )
        if not isinstance(self.parameter_fields, frozenset) or any(
            not isinstance(name, str) or not name.strip()
            for name in self.parameter_fields
        ):
            raise HarnessValidationError(
                "action definition parameter_fields must be non-empty strings"
            )


class ContextCompactionActionRegistry:
    def __init__(
        self,
        definitions: tuple[ContextCompactionActionDefinition, ...],
    ) -> None:
        if not definitions:
            raise HarnessValidationError(
                "context compaction action registry must not be empty"
            )
        registered: dict[
            ContextCompactionActionType,
            ContextCompactionActionDefinition,
        ] = {}
        for definition in definitions:
            if not isinstance(definition, ContextCompactionActionDefinition):
                raise HarnessValidationError(
                    "action registry values must be ContextCompactionActionDefinition"
                )
            if definition.action_type in registered:
                raise HarnessValidationError(
                    f"duplicate context action registration: {definition.action_type.value}"
                )
            registered[definition.action_type] = definition
        self._definitions = registered

    @classmethod
    def standard(cls) -> ContextCompactionActionRegistry:
        return cls(
            (
                ContextCompactionActionDefinition(
                    ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,
                    frozenset({"reconstruction_refs"}),
                ),
                ContextCompactionActionDefinition(
                    ContextCompactionActionType.REPLACE_WITH_REFERENCE,
                    frozenset({"reconstruction_refs"}),
                ),
                ContextCompactionActionDefinition(
                    ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET,
                    frozenset({"authorization_refs", "tool_ids"}),
                ),
                ContextCompactionActionDefinition(
                    ContextCompactionActionType.SELECT_EVIDENCE_SPANS,
                    frozenset(
                        {
                            "conflict_refs",
                            "lineage_refs",
                            "query_binding_ref",
                            "required_citation_refs",
                            "required_span_refs",
                            "selected_span_refs",
                            "source_refs",
                        }
                    ),
                ),
                ContextCompactionActionDefinition(
                    ContextCompactionActionType.COMPACT_OLD_CONVERSATION,
                    frozenset(
                        {
                            "complete_turn_group_ids",
                            "keep_recent_complete_turns",
                        }
                    ),
                ),
                ContextCompactionActionDefinition(
                    ContextCompactionActionType.SUMMARIZE_GROUPS,
                    frozenset({"allowed_loss_risks"}),
                ),
            )
        )

    def definition_for(
        self,
        action_type: ContextCompactionActionType | str,
    ) -> ContextCompactionActionDefinition:
        try:
            parsed = ContextCompactionActionType(action_type)
        except ValueError as exc:
            raise HarnessValidationError("unsupported compaction action") from exc
        definition = self._definitions.get(parsed)
        if definition is None:
            raise HarnessValidationError(
                f"unregistered compaction action: {parsed.value}"
            )
        return definition

    def validate_policy(self, policy: ContextCompactionPolicy) -> None:
        if not isinstance(policy, ContextCompactionPolicy):
            raise HarnessValidationError("policy must be ContextCompactionPolicy")
        seen_lossy = False
        for action_type in policy.action_order:
            self.definition_for(action_type)
            if action_type in REVERSIBLE_CONTEXT_ACTIONS:
                if seen_lossy:
                    raise HarnessValidationError(
                        "reversible context actions must precede lossy actions"
                    )
            else:
                seen_lossy = True

    def validate_action_shape(self, action: ContextCompactionAction) -> None:
        definition = self.definition_for(action.action_type)
        unknown = sorted(set(action.parameters).difference(definition.parameter_fields))
        missing = sorted(definition.parameter_fields.difference(action.parameters))
        if unknown or missing:
            details: list[str] = []
            if unknown:
                details.append("unknown=" + ",".join(unknown))
            if missing:
                details.append("missing=" + ",".join(missing))
            raise HarnessValidationError(
                f"invalid {action.action_type.value} parameters: " + "; ".join(details)
            )


class ContextCompactionPolicyResolver:
    def __init__(self, registry: ContextCompactionActionRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        value: Mapping[str, Any],
        *,
        parent: ContextCompactionPolicy | None = None,
    ) -> ContextCompactionPolicy:
        policy = ContextCompactionPolicy.from_dict(value)
        self._registry.validate_policy(policy)
        if parent is None:
            return policy
        self._registry.validate_policy(parent)
        effective = self._narrow(parent=parent, child=policy)
        self._registry.validate_policy(effective)
        return effective

    def _narrow(
        self,
        *,
        parent: ContextCompactionPolicy,
        child: ContextCompactionPolicy,
    ) -> ContextCompactionPolicy:
        child_actions = set(child.action_order)
        action_order = tuple(
            action for action in parent.action_order if action in child_actions
        )
        if not action_order:
            raise HarnessValidationError(
                "child context policy disables every parent-approved action"
            )
        allowed_loss_risks = tuple(
            risk for risk in parent.allowed_loss_risks if risk in child.allowed_loss_risks
        )
        effective_revision, _ = identity(
            "context-effective-policy",
            {
                "parent": parent.to_dict(),
                "child": child.to_dict(),
            },
        )
        return ContextCompactionPolicy(
            policy_revision=effective_revision,
            action_order=action_order,
            max_actions=min(parent.max_actions, child.max_actions),
            max_summary_calls=min(
                parent.max_summary_calls,
                child.max_summary_calls,
            ),
            max_replans=min(parent.max_replans, child.max_replans),
            max_llm_calls=min(parent.max_llm_calls, child.max_llm_calls),
            max_input_tokens=min(
                parent.max_input_tokens,
                child.max_input_tokens,
            ),
            max_cost_usd=min(parent.max_cost_usd, child.max_cost_usd),
            max_turns=min(parent.max_turns, child.max_turns),
            keep_recent_complete_turns=max(
                parent.keep_recent_complete_turns,
                child.keep_recent_complete_turns,
            ),
            protected_group_kinds=_ordered_union(
                parent.protected_group_kinds,
                child.protected_group_kinds,
            ),
            protected_reasons=_ordered_union(
                parent.protected_reasons,
                child.protected_reasons,
            ),
            allowed_loss_risks=allowed_loss_risks,
            failure_policy=_narrow_failure_policy(
                parent.failure_policy,
                child.failure_policy,
            ),
            metadata={
                "parent_policy_revision": parent.policy_revision,
                "child_policy_revision": child.policy_revision,
            },
        )


@dataclass(frozen=True)
class ContextCompactionPlanningRequest:
    source_snapshot: ContextSemanticSnapshot
    initial_admission: ContextPhysicalAdmissionEvidence
    policy: ContextCompactionPolicy
    budget_usage: ContextPlanningBudgetUsage = field(
        default_factory=ContextPlanningBudgetUsage
    )

    def __post_init__(self) -> None:
        if not isinstance(self.source_snapshot, ContextSemanticSnapshot):
            raise HarnessValidationError(
                "source_snapshot must be ContextSemanticSnapshot"
            )
        if self.source_snapshot.snapshot_kind is not ContextSemanticSnapshotKind.SOURCE:
            raise HarnessValidationError("planner requires a source semantic snapshot")
        if not isinstance(self.initial_admission, ContextPhysicalAdmissionEvidence):
            raise HarnessValidationError(
                "initial_admission must be ContextPhysicalAdmissionEvidence"
            )
        if not isinstance(self.policy, ContextCompactionPolicy):
            raise HarnessValidationError("policy must be ContextCompactionPolicy")
        if not isinstance(self.budget_usage, ContextPlanningBudgetUsage):
            raise HarnessValidationError(
                "budget_usage must be ContextPlanningBudgetUsage"
            )
        snapshot = self.source_snapshot
        admission = self.initial_admission
        if admission.source_snapshot_id != snapshot.snapshot_id:
            raise HarnessValidationError("initial admission source snapshot is stale")
        if admission.source_snapshot_checksum != snapshot.checksum:
            raise HarnessValidationError("initial admission source checksum is stale")
        if snapshot.policy_revision != self.policy.policy_revision:
            raise HarnessValidationError("source snapshot policy revision is stale")
        if snapshot.physical_profile_revision is None:
            raise HarnessValidationError(
                "source snapshot requires a resolved physical profile revision"
            )
        if (
            admission.physical_profile_revision
            != snapshot.physical_profile_revision
        ):
            raise HarnessValidationError("initial admission profile revision is stale")
        expected_group_ids = {group.group_id for group in snapshot.groups}
        if set(admission.group_input_tokens) != expected_group_ids:
            raise HarnessValidationError(
                "initial admission group counts must bind every source group"
            )


class ContextCompactionPlanValidator:
    def __init__(self, registry: ContextCompactionActionRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        plan: ContextCompactionPlan,
        *,
        source_snapshot: ContextSemanticSnapshot,
        policy: ContextCompactionPolicy,
        initial_admission: ContextPhysicalAdmissionEvidence,
        budget_usage: ContextPlanningBudgetUsage | None = None,
    ) -> None:
        if not isinstance(plan, ContextCompactionPlan):
            raise HarnessValidationError("plan must be ContextCompactionPlan")
        request = ContextCompactionPlanningRequest(
            source_snapshot=source_snapshot,
            initial_admission=initial_admission,
            policy=policy,
            budget_usage=budget_usage or ContextPlanningBudgetUsage(),
        )
        usage = request.budget_usage
        self._registry.validate_policy(policy)
        if plan.source_snapshot_id != source_snapshot.snapshot_id:
            raise HarnessValidationError("compaction plan source snapshot is stale")
        if plan.source_snapshot_checksum != source_snapshot.checksum:
            raise HarnessValidationError("compaction plan source checksum is stale")
        if plan.task_binding_ref != source_snapshot.task_binding_ref:
            raise HarnessValidationError("compaction plan task binding is stale")
        if plan.policy_revision != policy.policy_revision:
            raise HarnessValidationError("compaction plan policy revision is stale")
        if (
            plan.physical_profile_revision
            != initial_admission.physical_profile_revision
        ):
            raise HarnessValidationError("compaction plan profile revision is stale")
        if plan.initial_admission_ref != initial_admission.evidence_id:
            raise HarnessValidationError("compaction plan admission evidence is stale")
        target_input_tokens = min(
            policy.max_input_tokens,
            initial_admission.max_input_tokens,
        )
        if plan.target_input_tokens != target_input_tokens:
            raise HarnessValidationError("compaction plan input target is out of policy")
        expected_budgets = _remaining_budgets(policy, usage)
        if plan.max_actions != expected_budgets["actions"]:
            raise HarnessValidationError("compaction plan action budget is out of policy")
        if plan.max_summary_calls != expected_budgets["summary_calls"]:
            raise HarnessValidationError("compaction plan summary budget is out of policy")
        if plan.max_replans != expected_budgets["replans"]:
            raise HarnessValidationError("compaction plan replan budget is out of policy")
        if plan.max_llm_calls != expected_budgets["llm_calls"]:
            raise HarnessValidationError("compaction plan LLM budget is out of policy")
        if plan.max_cost_usd != expected_budgets["cost_usd"]:
            raise HarnessValidationError("compaction plan cost budget is out of policy")
        if plan.max_turns != expected_budgets["turns"]:
            raise HarnessValidationError("compaction plan turn budget is out of policy")
        protected_group_ids = _protected_group_ids(source_snapshot, policy)
        if plan.protected_group_ids != protected_group_ids:
            raise HarnessValidationError("compaction plan protected groups are stale")
        groups_by_id = {group.group_id: group for group in source_snapshot.groups}
        claimed_group_ids: set[str] = set()
        previous_order_index = -1
        for action in plan.actions:
            self._registry.validate_action_shape(action)
            if action.action_type not in policy.action_order:
                raise HarnessValidationError(
                    "compaction plan contains an out-of-policy action"
                )
            order_index = policy.action_order.index(action.action_type)
            if order_index < previous_order_index:
                raise HarnessValidationError(
                    "compaction plan action order is out of policy"
                )
            previous_order_index = order_index
            unknown_targets = set(action.target_group_ids).difference(groups_by_id)
            if unknown_targets:
                member_ids = {
                    member.member_id
                    for group in source_snapshot.groups
                    for member in group.members
                }
                if unknown_targets.intersection(member_ids):
                    raise HarnessValidationError(
                        "compaction actions must target complete groups, not members"
                    )
                raise HarnessValidationError(
                    "compaction action targets unknown source groups"
                )
            if claimed_group_ids.intersection(action.target_group_ids):
                raise HarnessValidationError(
                    "source group must not be targeted by multiple plan actions"
                )
            claimed_group_ids.update(action.target_group_ids)
            target_groups = tuple(
                groups_by_id[group_id] for group_id in action.target_group_ids
            )
            self._validate_action(
                action,
                target_groups=target_groups,
                source_snapshot=source_snapshot,
                policy=policy,
                protected_group_ids=set(protected_group_ids),
            )

    def _validate_action(
        self,
        action: ContextCompactionAction,
        *,
        target_groups: tuple[ContextGroup, ...],
        source_snapshot: ContextSemanticSnapshot,
        policy: ContextCompactionPolicy,
        protected_group_ids: set[str],
    ) -> None:
        action_type = action.action_type
        if action_type is ContextCompactionActionType.SELECT_EVIDENCE_SPANS:
            self._validate_evidence_action(
                action,
                target_groups=target_groups,
                source_snapshot=source_snapshot,
                policy=policy,
            )
            return
        if any(group.group_id in protected_group_ids for group in target_groups):
            raise HarnessValidationError("compaction action targets a protected group")
        if action_type is ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP:
            if any(
                group.group_kind is not ContextGroupKind.RECONSTRUCTABLE
                or group.reconstruction_policy is ContextReconstructionPolicy.NONE
                or group.reconstruction_ref is None
                for group in target_groups
            ):
                raise HarnessValidationError(
                    "drop action requires reconstructable complete groups"
                )
            _assert_parameter_refs(
                action,
                "reconstruction_refs",
                tuple(group.reconstruction_ref for group in target_groups),
            )
        elif action_type is ContextCompactionActionType.REPLACE_WITH_REFERENCE:
            if any(
                group.reconstruction_policy is ContextReconstructionPolicy.NONE
                or group.reconstruction_ref is None
                for group in target_groups
            ):
                raise HarnessValidationError(
                    "reference replacement requires durable reconstruction refs"
                )
            _assert_parameter_refs(
                action,
                "reconstruction_refs",
                tuple(group.reconstruction_ref for group in target_groups),
            )
        elif action_type is ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET:
            self._validate_tool_reduction(
                action,
                target_groups=target_groups,
                source_snapshot=source_snapshot,
            )
        elif action_type is ContextCompactionActionType.COMPACT_OLD_CONVERSATION:
            recent_tail = set(
                _recent_complete_tail_group_ids(
                    source_snapshot,
                    policy.keep_recent_complete_turns,
                )
            )
            if any(
                group.group_kind
                not in {
                    ContextGroupKind.CONVERSATION_TURN,
                    ContextGroupKind.TOOL_TRANSACTION,
                }
                or group.group_id in recent_tail
                or (
                    group.group_kind is ContextGroupKind.TOOL_TRANSACTION
                    and group.tool_transaction_state
                    is not ContextToolTransactionState.COMPLETED
                )
                for group in target_groups
            ):
                raise HarnessValidationError(
                    "conversation compaction must preserve the recent complete tail"
                )
            _assert_parameter_refs(
                action,
                "complete_turn_group_ids",
                action.target_group_ids,
            )
            if (
                action.parameters["keep_recent_complete_turns"]
                != policy.keep_recent_complete_turns
            ):
                raise HarnessValidationError(
                    "conversation compaction recent-tail policy is stale"
                )
        elif action_type is ContextCompactionActionType.SUMMARIZE_GROUPS:
            configured = _parameter_text_tuple(
                action,
                "allowed_loss_risks",
            )
            if configured != tuple(risk.value for risk in policy.allowed_loss_risks):
                raise HarnessValidationError(
                    "summary action loss-risk policy is stale"
                )

    def _validate_tool_reduction(
        self,
        action: ContextCompactionAction,
        *,
        target_groups: tuple[ContextGroup, ...],
        source_snapshot: ContextSemanticSnapshot,
    ) -> None:
        pending_tool_names = _pending_tool_names(source_snapshot)
        if any(
            group.group_kind is not ContextGroupKind.AUTHORIZED_TOOL_SCHEMA
            or group.semantic_metadata.get("reachable") is not False
            or group.semantic_metadata.get("tool_id") in pending_tool_names
            for group in target_groups
        ):
            raise HarnessValidationError(
                "tool reduction requires unreachable currently authorized tools"
            )
        _assert_parameter_refs(
            action,
            "tool_ids",
            tuple(str(group.semantic_metadata["tool_id"]) for group in target_groups),
        )
        _assert_parameter_refs(
            action,
            "authorization_refs",
            tuple(
                str(group.semantic_metadata["authorization_ref"])
                for group in target_groups
            ),
        )

    def _validate_evidence_action(
        self,
        action: ContextCompactionAction,
        *,
        target_groups: tuple[ContextGroup, ...],
        source_snapshot: ContextSemanticSnapshot,
        policy: ContextCompactionPolicy,
    ) -> None:
        if len(target_groups) != 1:
            raise HarnessValidationError(
                "evidence selection must target exactly one evidence group"
            )
        group = target_groups[0]
        if group.group_kind is not ContextGroupKind.EVIDENCE:
            raise HarnessValidationError(
                "evidence selection must target an evidence group"
            )
        if ContextGroupKind.EVIDENCE in policy.protected_group_kinds:
            raise HarnessValidationError("policy protects the complete evidence group")
        if set(group.protection_reasons).difference(
            {ContextProtectionReason.REQUIRED_EVIDENCE}
        ):
            raise HarnessValidationError(
                "evidence selection targets a non-evidence protected group"
            )
        if group.semantic_metadata.get("whole_group_required") is True:
            raise HarnessValidationError("required evidence group cannot be reduced")
        selected = _parameter_text_tuple(action, "selected_span_refs")
        required = _parameter_text_tuple(action, "required_span_refs")
        all_spans = tuple(member.content_ref for member in group.members)
        if not selected or not set(selected).issubset(all_spans):
            raise HarnessValidationError(
                "evidence selection contains unknown or empty span refs"
            )
        if not set(required).issubset(selected):
            raise HarnessValidationError(
                "evidence selection removes required span refs"
            )
        if selected != tuple(group.semantic_metadata.get("selected_span_refs", ())):
            raise HarnessValidationError("evidence selection refs are stale")
        if required != tuple(group.semantic_metadata.get("required_span_refs", ())):
            raise HarnessValidationError("required evidence span refs are stale")
        query_binding_ref = required_text(
            action.parameters["query_binding_ref"],
            field="query_binding_ref",
        )
        if (
            query_binding_ref != source_snapshot.task_binding_ref
            or query_binding_ref != group.query_binding_ref
        ):
            raise HarnessValidationError("evidence selection query binding is stale")
        _assert_parameter_refs(action, "source_refs", group.source_refs)
        _assert_parameter_refs(
            action,
            "lineage_refs",
            tuple(group.semantic_metadata.get("lineage_refs", ())),
        )
        _assert_parameter_refs(
            action,
            "conflict_refs",
            tuple(group.semantic_metadata.get("conflict_refs", ())),
        )
        _assert_parameter_refs(
            action,
            "required_citation_refs",
            group.required_citation_refs,
        )


class ContextCompactionPlanner:
    def __init__(
        self,
        registry: ContextCompactionActionRegistry | None = None,
    ) -> None:
        self._registry = registry or ContextCompactionActionRegistry.standard()
        self._validator = ContextCompactionPlanValidator(self._registry)

    def plan(
        self,
        request: ContextCompactionPlanningRequest,
    ) -> ContextCompactionPlanningResult:
        if not isinstance(request, ContextCompactionPlanningRequest):
            raise HarnessValidationError(
                "request must be ContextCompactionPlanningRequest"
            )
        policy = request.policy
        snapshot = request.source_snapshot
        admission = request.initial_admission
        usage = request.budget_usage
        self._registry.validate_policy(policy)
        protected_group_ids = _protected_group_ids(snapshot, policy)
        target_input_tokens = min(
            policy.max_input_tokens,
            admission.max_input_tokens,
        )
        if admission.admitted and admission.input_tokens <= target_input_tokens:
            return self._result(
                request,
                status=ContextCompactionPlanningStatus.NO_COMPACTION_REQUIRED,
                protected_group_ids=protected_group_ids,
                reason_code="source_physical_admission_passed",
            )
        if (
            not admission.admitted
            and admission.admission_status != "input_limit_exceeded"
        ):
            return self._result(
                request,
                status=ContextCompactionPlanningStatus.NO_ALLOWED_COMPACTION,
                protected_group_ids=protected_group_ids,
                reason_code="physical_admission_failure_is_not_compactable",
            )
        remaining = _remaining_budgets(policy, usage)
        if remaining["actions"] < 1:
            return self._result(
                request,
                status=ContextCompactionPlanningStatus.ACTION_BUDGET_EXHAUSTED,
                protected_group_ids=protected_group_ids,
                reason_code="action_budget_exhausted_before_planning",
            )
        if remaining["turns"] < 1:
            return self._result(
                request,
                status=ContextCompactionPlanningStatus.NO_ALLOWED_COMPACTION,
                protected_group_ids=protected_group_ids,
                reason_code="turn_budget_exhausted_before_planning",
            )
        candidates = self._candidate_actions(
            snapshot=snapshot,
            policy=policy,
            remaining=remaining,
            protected_group_ids=set(protected_group_ids),
        )
        evidence_selection_targets = {
            group_id
            for action in candidates
            if action.action_type is ContextCompactionActionType.SELECT_EVIDENCE_SPANS
            for group_id in action.target_group_ids
        }
        hard_protected_ids = set(protected_group_ids).difference(
            evidence_selection_targets
        )
        protected_input_tokens = admission.fixed_input_tokens + sum(
            admission.group_input_tokens[group_id]
            for group_id in hard_protected_ids
        )
        if protected_input_tokens > target_input_tokens:
            return self._result(
                request,
                status=(
                    ContextCompactionPlanningStatus.PROTECTED_CONTEXT_EXCEEDS_WINDOW
                ),
                protected_group_ids=protected_group_ids,
                reason_code="hard_protected_context_exceeds_target",
            )
        if not candidates:
            return self._result(
                request,
                status=ContextCompactionPlanningStatus.NO_ALLOWED_COMPACTION,
                protected_group_ids=protected_group_ids,
                reason_code="no_registered_action_has_satisfied_preconditions",
            )
        actions = candidates[: remaining["actions"]]
        plan = ContextCompactionPlan(
            source_snapshot_id=snapshot.snapshot_id,
            source_snapshot_checksum=snapshot.checksum,
            task_binding_ref=snapshot.task_binding_ref,
            target_input_tokens=target_input_tokens,
            max_actions=remaining["actions"],
            max_summary_calls=remaining["summary_calls"],
            max_replans=remaining["replans"],
            max_llm_calls=remaining["llm_calls"],
            max_cost_usd=remaining["cost_usd"],
            max_turns=remaining["turns"],
            actions=actions,
            protected_group_ids=protected_group_ids,
            policy_revision=policy.policy_revision,
            physical_profile_revision=admission.physical_profile_revision,
            initial_admission_ref=admission.evidence_id,
        )
        self._validator.validate(
            plan,
            source_snapshot=snapshot,
            policy=policy,
            initial_admission=admission,
            budget_usage=usage,
        )
        return self._result(
            request,
            status=ContextCompactionPlanningStatus.PLAN_READY,
            protected_group_ids=protected_group_ids,
            reason_code="deterministic_plan_ready",
            plan=plan,
        )

    def _candidate_actions(
        self,
        *,
        snapshot: ContextSemanticSnapshot,
        policy: ContextCompactionPolicy,
        remaining: Mapping[str, Any],
        protected_group_ids: set[str],
    ) -> tuple[ContextCompactionAction, ...]:
        actions: list[ContextCompactionAction] = []
        claimed_group_ids: set[str] = set()
        pending_tool_names = _pending_tool_names(snapshot)
        groups = snapshot.groups
        for action_type in policy.action_order:
            if action_type is ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP:
                targets = tuple(
                    group
                    for group in groups
                    if group.group_kind is ContextGroupKind.RECONSTRUCTABLE
                    and group.reconstruction_policy
                    is not ContextReconstructionPolicy.NONE
                    and group.reconstruction_ref is not None
                    and group.group_id not in protected_group_ids
                    and group.group_id not in claimed_group_ids
                )
                action = _reference_action(
                    action_type,
                    targets,
                )
                if action is not None:
                    actions.append(action)
                    claimed_group_ids.update(action.target_group_ids)
            elif action_type is ContextCompactionActionType.REPLACE_WITH_REFERENCE:
                targets = tuple(
                    group
                    for group in groups
                    if group.group_kind
                    not in {
                        ContextGroupKind.RECONSTRUCTABLE,
                        ContextGroupKind.AUTHORIZED_TOOL_SCHEMA,
                    }
                    and group.reconstruction_policy
                    is not ContextReconstructionPolicy.NONE
                    and group.reconstruction_ref is not None
                    and group.group_id not in protected_group_ids
                    and group.group_id not in claimed_group_ids
                )
                action = _reference_action(action_type, targets)
                if action is not None:
                    actions.append(action)
                    claimed_group_ids.update(action.target_group_ids)
            elif action_type is ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET:
                targets = tuple(
                    group
                    for group in groups
                    if group.group_kind is ContextGroupKind.AUTHORIZED_TOOL_SCHEMA
                    and group.semantic_metadata.get("reachable") is False
                    and group.semantic_metadata.get("tool_id") not in pending_tool_names
                    and group.group_id not in protected_group_ids
                    and group.group_id not in claimed_group_ids
                )
                if targets:
                    action = ContextCompactionAction(
                        action_type=action_type,
                        target_group_ids=tuple(group.group_id for group in targets),
                        parameters={
                            "tool_ids": tuple(
                                str(group.semantic_metadata["tool_id"])
                                for group in targets
                            ),
                            "authorization_refs": tuple(
                                str(group.semantic_metadata["authorization_ref"])
                                for group in targets
                            ),
                        },
                    )
                    actions.append(action)
                    claimed_group_ids.update(action.target_group_ids)
            elif action_type is ContextCompactionActionType.SELECT_EVIDENCE_SPANS:
                for group in groups:
                    selection = _evidence_selection_parameters(
                        group,
                        snapshot=snapshot,
                        policy=policy,
                    )
                    if (
                        selection is None
                        or group.group_id in claimed_group_ids
                    ):
                        continue
                    action = ContextCompactionAction(
                        action_type=action_type,
                        target_group_ids=(group.group_id,),
                        parameters=selection,
                    )
                    actions.append(action)
                    claimed_group_ids.add(group.group_id)
            elif action_type is ContextCompactionActionType.COMPACT_OLD_CONVERSATION:
                recent_tail = set(
                    _recent_complete_tail_group_ids(
                        snapshot,
                        policy.keep_recent_complete_turns,
                    )
                )
                old_turn_group_ids = tuple(
                    group_id
                    for unit in _complete_conversation_units(snapshot)
                    for group_id in unit
                    if group_id not in recent_tail
                )
                targets = tuple(
                    group_id
                    for group_id in old_turn_group_ids
                    if group_id not in protected_group_ids
                    and group_id not in claimed_group_ids
                )
                if targets:
                    action = ContextCompactionAction(
                        action_type=action_type,
                        target_group_ids=targets,
                        parameters={
                            "complete_turn_group_ids": targets,
                            "keep_recent_complete_turns": (
                                policy.keep_recent_complete_turns
                            ),
                        },
                    )
                    actions.append(action)
                    claimed_group_ids.update(targets)
            elif action_type is ContextCompactionActionType.SUMMARIZE_GROUPS:
                if (
                    remaining["summary_calls"] < 1
                    or remaining["llm_calls"] < 1
                    or remaining["cost_usd"] <= 0
                ):
                    continue
                targets = tuple(
                    group.group_id
                    for group in groups
                    if group.group_id not in protected_group_ids
                    and group.group_id not in claimed_group_ids
                    and _summary_eligible(group)
                )
                if targets:
                    action = ContextCompactionAction(
                        action_type=action_type,
                        target_group_ids=targets,
                        parameters={
                            "allowed_loss_risks": tuple(
                                risk.value for risk in policy.allowed_loss_risks
                            )
                        },
                    )
                    actions.append(action)
                    claimed_group_ids.update(targets)
        return tuple(actions)

    @staticmethod
    def _result(
        request: ContextCompactionPlanningRequest,
        *,
        status: ContextCompactionPlanningStatus,
        protected_group_ids: tuple[str, ...],
        reason_code: str,
        plan: ContextCompactionPlan | None = None,
    ) -> ContextCompactionPlanningResult:
        return ContextCompactionPlanningResult(
            status=status,
            source_snapshot_id=request.source_snapshot.snapshot_id,
            source_snapshot_checksum=request.source_snapshot.checksum,
            admission_evidence_id=request.initial_admission.evidence_id,
            protected_group_ids=protected_group_ids,
            reason_code=reason_code,
            plan=plan,
        )


def _reference_action(
    action_type: ContextCompactionActionType,
    groups: tuple[ContextGroup, ...],
) -> ContextCompactionAction | None:
    if not groups:
        return None
    return ContextCompactionAction(
        action_type=action_type,
        target_group_ids=tuple(group.group_id for group in groups),
        parameters={
            "reconstruction_refs": tuple(group.reconstruction_ref for group in groups)
        },
    )


def _evidence_selection_parameters(
    group: ContextGroup,
    *,
    snapshot: ContextSemanticSnapshot,
    policy: ContextCompactionPolicy,
) -> dict[str, Any] | None:
    if group.group_kind is not ContextGroupKind.EVIDENCE:
        return None
    if ContextGroupKind.EVIDENCE in policy.protected_group_kinds:
        return None
    if set(group.protection_reasons).difference(
        {ContextProtectionReason.REQUIRED_EVIDENCE}
    ):
        return None
    if group.semantic_metadata.get("whole_group_required") is True:
        return None
    all_spans = tuple(member.content_ref for member in group.members)
    selected = tuple(group.semantic_metadata.get("selected_span_refs", ()))
    required = tuple(group.semantic_metadata.get("required_span_refs", ()))
    if (
        not selected
        or selected == all_spans
        or not set(selected).issubset(all_spans)
        or not set(required).issubset(selected)
        or group.query_binding_ref != snapshot.task_binding_ref
    ):
        return None
    return {
        "selected_span_refs": selected,
        "required_span_refs": required,
        "query_binding_ref": snapshot.task_binding_ref,
        "source_refs": group.source_refs,
        "lineage_refs": tuple(group.semantic_metadata.get("lineage_refs", ())),
        "conflict_refs": tuple(group.semantic_metadata.get("conflict_refs", ())),
        "required_citation_refs": group.required_citation_refs,
    }


def _protected_group_ids(
    snapshot: ContextSemanticSnapshot,
    policy: ContextCompactionPolicy,
) -> tuple[str, ...]:
    recent_tail = set(
        _recent_complete_tail_group_ids(
            snapshot,
            policy.keep_recent_complete_turns,
        )
    )
    return tuple(
        group.group_id
        for group in snapshot.groups
        if group.protected
        or group.group_kind in policy.protected_group_kinds
        or bool(set(group.protection_reasons).intersection(policy.protected_reasons))
        or group.group_id in recent_tail
    )


def _complete_conversation_units(
    snapshot: ContextSemanticSnapshot,
) -> tuple[tuple[str, ...], ...]:
    units: list[tuple[str, ...]] = []
    current: list[str] = []
    for group in snapshot.groups:
        if group.group_kind is ContextGroupKind.CONVERSATION_TURN:
            role = group.semantic_metadata.get("role")
            if role == "user":
                current = [group.group_id]
            elif role == "assistant" and current:
                current.append(group.group_id)
                units.append(tuple(current))
                current = []
        elif (
            group.group_kind is ContextGroupKind.TOOL_TRANSACTION
            and group.tool_transaction_state is ContextToolTransactionState.COMPLETED
            and current
        ):
            current.append(group.group_id)
    return tuple(units)


def _recent_complete_tail_group_ids(
    snapshot: ContextSemanticSnapshot,
    keep_recent_complete_turns: int,
) -> tuple[str, ...]:
    if keep_recent_complete_turns < 1:
        return ()
    units = _complete_conversation_units(snapshot)
    return tuple(
        group_id
        for unit in units[-keep_recent_complete_turns:]
        for group_id in unit
    )


def _pending_tool_names(snapshot: ContextSemanticSnapshot) -> set[str]:
    return {
        str(group.semantic_metadata["tool_name"])
        for group in snapshot.groups
        if group.group_kind is ContextGroupKind.TOOL_TRANSACTION
        and group.tool_transaction_state
        in {
            ContextToolTransactionState.PENDING,
            ContextToolTransactionState.UNRESOLVED,
        }
        and group.semantic_metadata.get("tool_name") is not None
    }


def _summary_eligible(group: ContextGroup) -> bool:
    if group.group_kind is ContextGroupKind.TOOL_TRANSACTION:
        return group.tool_transaction_state is ContextToolTransactionState.COMPLETED
    return group.group_kind in {
        ContextGroupKind.CONVERSATION_TURN,
        ContextGroupKind.EVIDENCE,
        ContextGroupKind.MEMORY_REFERENCE,
        ContextGroupKind.RUN_STATE,
    }


def _remaining_budgets(
    policy: ContextCompactionPolicy,
    usage: ContextPlanningBudgetUsage,
) -> dict[str, Any]:
    return {
        "actions": max(0, policy.max_actions - usage.actions),
        "summary_calls": max(0, policy.max_summary_calls - usage.summary_calls),
        "replans": max(0, policy.max_replans - usage.replans),
        "llm_calls": max(0, policy.max_llm_calls - usage.llm_calls),
        "cost_usd": max(0.0, policy.max_cost_usd - usage.cost_usd),
        "turns": max(0, policy.max_turns - usage.turns),
    }


def _parameter_text_tuple(
    action: ContextCompactionAction,
    field_name: str,
) -> tuple[str, ...]:
    return text_tuple(action.parameters[field_name], field=field_name)


def _assert_parameter_refs(
    action: ContextCompactionAction,
    field_name: str,
    expected: tuple[str, ...],
) -> None:
    actual = _parameter_text_tuple(action, field_name)
    if actual != expected:
        raise HarnessValidationError(
            f"{action.action_type.value} {field_name} are stale or unauthorized"
        )


def _ordered_union(first: tuple[Any, ...], second: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _narrow_failure_policy(parent: str, child: str) -> str:
    if parent == "halt" or child == "halt":
        return "halt"
    return parent


__all__ = [
    "ContextCompactionActionDefinition",
    "ContextCompactionActionRegistry",
    "ContextCompactionPlanner",
    "ContextCompactionPlanningRequest",
    "ContextCompactionPlanValidator",
    "ContextCompactionPolicyResolver",
]
