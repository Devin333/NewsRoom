from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from framework.harness.context.compaction_models import (
    ContextCompactionActionResult,
    ContextCompactionOutcome,
    ContextCompactionPlan,
    ContextCompactionPolicy,
)
from framework.harness.context.group_models import (
    ContextGroup,
    ContextGroupKind,
    ContextProtectionReason,
    ContextToolTransactionState,
)
from framework.harness.context.planning import _protected_group_ids
from framework.harness.context.planning_models import (
    ContextPhysicalAdmissionEvidence,
    ContextPlanningBudgetUsage,
)
from framework.harness.context.verified_common import (
    frozen_mapping,
    required_text,
    text_tuple,
)
from framework.harness.context.verified_records import ContextSemanticSnapshot
from framework.harness.control_plane.errors import HarnessValidationError


@dataclass(frozen=True)
class ContextPhysicalMaterialization:
    result_snapshot: ContextSemanticSnapshot
    deployment_id: str
    profile_revision: str
    materialization_revision: str
    request: Any = field(repr=False)
    fixed_input_tokens: int
    group_input_tokens: Mapping[str, int]
    diagnostic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.result_snapshot, ContextSemanticSnapshot):
            raise HarnessValidationError(
                "result_snapshot must be ContextSemanticSnapshot"
            )
        if (
            self.result_snapshot.physical_profile_revision
            != self.profile_revision
        ):
            raise HarnessValidationError(
                "physical materialization profile revision is stale"
            )
        if not isinstance(self.deployment_id, str) or not self.deployment_id.strip():
            raise HarnessValidationError("deployment_id is required")
        if not isinstance(self.profile_revision, str) or not self.profile_revision.strip():
            raise HarnessValidationError("profile_revision is required")
        if (
            not isinstance(self.materialization_revision, str)
            or not self.materialization_revision.strip()
        ):
            raise HarnessValidationError("materialization_revision is required")
        if isinstance(self.fixed_input_tokens, bool) or not isinstance(
            self.fixed_input_tokens,
            int,
        ) or self.fixed_input_tokens < 0:
            raise HarnessValidationError(
                "fixed_input_tokens must be a non-negative integer"
            )
        if not isinstance(self.group_input_tokens, Mapping):
            raise HarnessValidationError("group_input_tokens must be an object")
        parsed = {
            required_text(group_id, field="group_input_tokens.group_id"): count
            for group_id, count in self.group_input_tokens.items()
        }
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in parsed.values()
        ):
            raise HarnessValidationError(
                "group_input_tokens values must be non-negative integers"
            )
        expected = {group.group_id for group in self.result_snapshot.groups}
        if set(parsed) != expected:
            raise HarnessValidationError(
                "physical materialization counts must bind every result group"
            )
        object.__setattr__(self, "deployment_id", self.deployment_id.strip())
        object.__setattr__(self, "profile_revision", self.profile_revision.strip())
        object.__setattr__(
            self,
            "materialization_revision",
            self.materialization_revision.strip(),
        )
        object.__setattr__(self, "group_input_tokens", frozen_mapping(parsed, field="group_input_tokens"))
        object.__setattr__(
            self,
            "diagnostic_metadata",
            frozen_mapping(self.diagnostic_metadata, field="diagnostic_metadata"),
        )


@runtime_checkable
class ContextPhysicalAdmissionVerifier(Protocol):
    def admit(
        self,
        materialization: ContextPhysicalMaterialization,
    ) -> ContextPhysicalAdmissionEvidence:
        ...


@dataclass(frozen=True)
class ContextAggregateGateResult:
    gate_name: str
    passed: bool
    input_ref: str
    result_ref: str
    reason_code: str
    details: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for field_name in (
            "gate_name",
            "input_ref",
            "result_ref",
            "reason_code",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        if "@" not in self.gate_name:
            raise HarnessValidationError("aggregate gate_name must include a version")
        if not isinstance(self.passed, bool):
            raise HarnessValidationError("aggregate gate passed must be a boolean")
        object.__setattr__(
            self,
            "details",
            frozen_mapping(self.details, field="details"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "input_ref": self.input_ref,
            "result_ref": self.result_ref,
            "reason_code": self.reason_code,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ContextAggregateVerificationResult:
    source_snapshot_id: str
    source_snapshot_checksum: str
    result_snapshot_id: str
    result_snapshot_checksum: str
    physical_admission_evidence_id: str
    gates: tuple[ContextAggregateGateResult, ...]
    passed: bool
    outcome: ContextCompactionOutcome | str
    reason_code: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_snapshot_id",
            "source_snapshot_checksum",
            "result_snapshot_id",
            "result_snapshot_checksum",
            "physical_admission_evidence_id",
            "reason_code",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        gates = tuple(self.gates)
        if not gates or not all(
            isinstance(gate, ContextAggregateGateResult) for gate in gates
        ):
            raise HarnessValidationError(
                "aggregate verification requires versioned gate results"
            )
        refs = {
            (gate.input_ref, gate.result_ref)
            for gate in gates
        }
        if len(refs) != 1:
            raise HarnessValidationError(
                "aggregate gates must bind the same source/result refs"
            )
        if refs != {(self.source_snapshot_checksum, self.result_snapshot_checksum)}:
            raise HarnessValidationError(
                "aggregate gate references do not bind declared source/result checksums"
            )
        if not isinstance(self.passed, bool):
            raise HarnessValidationError("aggregate passed must be a boolean")
        object.__setattr__(self, "gates", gates)
        object.__setattr__(self, "outcome", ContextCompactionOutcome(self.outcome))
        if self.passed != (
            self.outcome is ContextCompactionOutcome.VERIFIED
            and all(gate.passed for gate in gates)
        ):
            raise HarnessValidationError(
                "aggregate passed must match all gates and VERIFIED outcome"
            )

    @property
    def dispatch_authorized(self) -> bool:
        return self.passed and self.outcome is ContextCompactionOutcome.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_checksum": self.source_snapshot_checksum,
            "result_snapshot_id": self.result_snapshot_id,
            "result_snapshot_checksum": self.result_snapshot_checksum,
            "physical_admission_evidence_id": self.physical_admission_evidence_id,
            "gates": [gate.to_dict() for gate in self.gates],
            "passed": self.passed,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "dispatch_authorized": self.dispatch_authorized,
        }


class ContextAggregateVerifier:
    REQUIRED_GATES = (
        "context_structure@1",
        "context_protection@1",
        "context_tool_transaction@1",
        "context_provenance@1",
        "context_evidence_loss@1",
        "context_action_budget@1",
        "context_snapshot_integrity@1",
        "context_physical_admission@1",
    )

    def verify(
        self,
        *,
        source_snapshot: ContextSemanticSnapshot,
        result_snapshot: ContextSemanticSnapshot,
        plan: ContextCompactionPlan,
        policy: ContextCompactionPolicy,
        action_results: tuple[ContextCompactionActionResult, ...],
        usage: ContextPlanningBudgetUsage,
        physical_admission: ContextPhysicalAdmissionEvidence,
    ) -> ContextAggregateVerificationResult:
        if not isinstance(source_snapshot, ContextSemanticSnapshot):
            raise HarnessValidationError("source_snapshot must be ContextSemanticSnapshot")
        if not isinstance(result_snapshot, ContextSemanticSnapshot):
            raise HarnessValidationError("result_snapshot must be ContextSemanticSnapshot")
        if not isinstance(plan, ContextCompactionPlan):
            raise HarnessValidationError("plan must be ContextCompactionPlan")
        if not isinstance(policy, ContextCompactionPolicy):
            raise HarnessValidationError("policy must be ContextCompactionPolicy")
        if not isinstance(physical_admission, ContextPhysicalAdmissionEvidence):
            raise HarnessValidationError(
                "physical_admission must be ContextPhysicalAdmissionEvidence"
            )
        gate_functions = (
            ("context_structure@1", self._structure_gate),
            ("context_protection@1", self._protection_gate),
            ("context_tool_transaction@1", self._tool_gate),
            ("context_provenance@1", self._provenance_gate),
            ("context_evidence_loss@1", self._evidence_gate),
            ("context_action_budget@1", self._budget_gate),
            ("context_snapshot_integrity@1", self._snapshot_gate),
            ("context_physical_admission@1", self._physical_gate),
        )
        gates: list[ContextAggregateGateResult] = []
        for gate_name, evaluator in gate_functions:
            passed, reason_code, details = evaluator(
                source_snapshot=source_snapshot,
                result_snapshot=result_snapshot,
                plan=plan,
                policy=policy,
                action_results=action_results,
                usage=usage,
                physical_admission=physical_admission,
            )
            gates.append(
                ContextAggregateGateResult(
                    gate_name=gate_name,
                    passed=passed,
                    input_ref=source_snapshot.checksum,
                    result_ref=result_snapshot.checksum,
                    reason_code=reason_code,
                    details=details,
                )
            )
        passed = all(gate.passed for gate in gates)
        return ContextAggregateVerificationResult(
            source_snapshot_id=source_snapshot.snapshot_id,
            source_snapshot_checksum=source_snapshot.checksum,
            result_snapshot_id=result_snapshot.snapshot_id,
            result_snapshot_checksum=result_snapshot.checksum,
            physical_admission_evidence_id=physical_admission.evidence_id,
            gates=tuple(gates),
            passed=passed,
            outcome=(
                ContextCompactionOutcome.VERIFIED
                if passed
                else ContextCompactionOutcome.POST_COMPACTION_VERIFY_FAILED
            ),
            reason_code=(
                "all_aggregate_gates_passed"
                if passed
                else "one_or_more_aggregate_gates_failed"
            ),
        )

    def _structure_gate(self, *, source_snapshot, result_snapshot, **_) -> tuple[bool, str, dict[str, Any]]:
        group_ids = [group.group_id for group in result_snapshot.groups]
        unique = len(group_ids) == len(set(group_ids))
        tool_members_outside = [
            member.member_id
            for group in result_snapshot.groups
            if group.group_kind is not ContextGroupKind.TOOL_TRANSACTION
            for member in group.members
            if member.member_kind.value in {"tool_call", "tool_result"}
        ]
        passed = unique and not tool_members_outside
        return (
            passed,
            "structure_valid" if passed else "result_structure_invalid",
            {"duplicate_group_ids": not unique, "tool_members_outside_transaction": tool_members_outside},
        )

    def _protection_gate(self, *, source_snapshot, result_snapshot, policy, **_) -> tuple[bool, str, dict[str, Any]]:
        protected_ids = set(_protected_group_ids(source_snapshot, policy))
        result_ids = {group.group_id for group in result_snapshot.groups}
        missing = protected_ids.difference(result_ids)
        allowed_missing: set[str] = set()
        for source_group in source_snapshot.groups:
            if source_group.group_id not in missing:
                continue
            if source_group.group_kind is not ContextGroupKind.EVIDENCE:
                continue
            if set(source_group.protection_reasons).difference(
                {ContextProtectionReason.REQUIRED_EVIDENCE}
            ):
                continue
            if any(
                source_group.group_id
                in set(result_group.semantic_metadata.get("covered_group_ids", ()))
                for result_group in result_snapshot.groups
            ):
                allowed_missing.add(source_group.group_id)
        unresolved = sorted(missing.difference(allowed_missing))
        weakened = [
            group.group_id
            for group in source_snapshot.groups
            if group.group_id in result_ids
            and not set(group.protection_reasons).issubset(
                set(next(result for result in result_snapshot.groups if result.group_id == group.group_id).protection_reasons)
            )
        ]
        passed = not unresolved and not weakened
        return (
            passed,
            "protected_content_preserved" if passed else "protected_content_missing_or_weakened",
            {"missing_group_ids": unresolved, "weakened_group_ids": weakened},
        )

    def _tool_gate(self, *, source_snapshot, result_snapshot, **_) -> tuple[bool, str, dict[str, Any]]:
        result_ids = {group.group_id for group in result_snapshot.groups}
        pending = [
            group.group_id
            for group in source_snapshot.groups
            if group.group_kind is ContextGroupKind.TOOL_TRANSACTION
            and group.tool_transaction_state
            in {
                ContextToolTransactionState.PENDING,
                ContextToolTransactionState.UNRESOLVED,
            }
            and group.group_id not in result_ids
        ]
        invalid = [
            group.group_id
            for group in result_snapshot.groups
            if group.group_kind is ContextGroupKind.TOOL_TRANSACTION
            and (
                group.tool_transaction_state
                is ContextToolTransactionState.COMPLETED
                and not any(
                    member.member_kind.value == "tool_result"
                    for member in group.members
                )
            )
        ]
        passed = not pending and not invalid
        return (
            passed,
            "tool_transactions_valid" if passed else "tool_transaction_integrity_failed",
            {"pending_missing": pending, "invalid_transactions": invalid},
        )

    def _provenance_gate(self, *, source_snapshot, result_snapshot, action_results, **_) -> tuple[bool, str, dict[str, Any]]:
        source_refs = {
            ref
            for group in source_snapshot.groups
            for ref in (
                *group.source_refs,
                *(ref for member in group.members for ref in member.source_refs),
            )
            if isinstance(ref, str)
        }
        # Keep group/member source refs bounded and reject newly invented
        # provenance. Durable artifact refs are carried separately by action results.
        missing: list[str] = []
        for group in result_snapshot.groups:
            missing.extend(ref for ref in group.source_refs if ref not in source_refs)
            for member in group.members:
                missing.extend(ref for ref in member.source_refs if ref not in source_refs)
        passed = not missing
        return (
            passed,
            "provenance_valid" if passed else "result_provenance_contains_unknown_refs",
            {"unknown_refs": sorted(set(missing))},
        )

    def _evidence_gate(self, *, source_snapshot, result_snapshot, action_results, policy, **_) -> tuple[bool, str, dict[str, Any]]:
        required_refs = {
            ref
            for group in source_snapshot.groups
            if group.group_kind is ContextGroupKind.EVIDENCE
            for ref in (
                *group.required_citation_refs,
                *tuple(group.semantic_metadata.get("required_span_refs", ())),
                *tuple(group.semantic_metadata.get("conflict_refs", ())),
            )
        }
        omitted_required = [
            ref
            for action_result in action_results
            for ref in action_result.loss_report.omitted_span_refs
            if ref in required_refs
        ]
        disallowed_risk = [
            action_result.loss_report.loss_risk.value
            for action_result in action_results
            if action_result.loss_report.loss_risk not in policy.allowed_loss_risks
        ]
        passed = not omitted_required and not disallowed_risk
        return (
            passed,
            "evidence_and_loss_valid" if passed else "evidence_or_loss_gate_failed",
            {"omitted_required_refs": sorted(set(omitted_required)), "disallowed_loss_risks": disallowed_risk},
        )

    def _budget_gate(self, *, plan, action_results, usage, **_) -> tuple[bool, str, dict[str, Any]]:
        summary_calls = sum(
            result.action.action_type.value == "summarize_groups"
            for result in action_results
        )
        passed = (
            len(action_results) <= plan.max_actions
            and summary_calls <= plan.max_summary_calls
            and usage.actions <= plan.max_actions
            and usage.summary_calls <= plan.max_summary_calls
            and usage.llm_calls <= plan.max_llm_calls
            and usage.cost_usd <= plan.max_cost_usd
            and usage.turns <= plan.max_turns
        )
        return (
            passed,
            "action_budgets_valid" if passed else "action_or_worker_budget_exceeded",
            {
                "actions": len(action_results),
                "summary_calls": summary_calls,
                "usage": usage.to_dict(),
                "bounds": {
                    "max_actions": plan.max_actions,
                    "max_summary_calls": plan.max_summary_calls,
                    "max_llm_calls": plan.max_llm_calls,
                    "max_cost_usd": plan.max_cost_usd,
                    "max_turns": plan.max_turns,
                },
            },
        )

    def _snapshot_gate(self, *, source_snapshot, result_snapshot, plan, **_) -> tuple[bool, str, dict[str, Any]]:
        passed = (
            result_snapshot.parent_snapshot_id == source_snapshot.snapshot_id
            and plan.source_snapshot_id == source_snapshot.snapshot_id
            and plan.source_snapshot_checksum == source_snapshot.checksum
            and result_snapshot.snapshot_id != source_snapshot.snapshot_id
            and bool(result_snapshot.checksum)
        )
        return (
            passed,
            "snapshot_integrity_valid" if passed else "snapshot_integrity_failed",
            {
                "source_snapshot_id": source_snapshot.snapshot_id,
                "result_snapshot_id": result_snapshot.snapshot_id,
                "parent_snapshot_id": result_snapshot.parent_snapshot_id,
            },
        )

    def _physical_gate(self, *, result_snapshot, physical_admission, **_) -> tuple[bool, str, dict[str, Any]]:
        passed = (
            physical_admission.source_snapshot_id == result_snapshot.snapshot_id
            and physical_admission.source_snapshot_checksum == result_snapshot.checksum
            and physical_admission.physical_profile_revision
            == result_snapshot.physical_profile_revision
            and physical_admission.admitted
            and physical_admission.admission_status == "admitted"
            and set(physical_admission.group_input_tokens)
            == {group.group_id for group in result_snapshot.groups}
        )
        return (
            passed,
            "prepared_physical_admission_passed"
            if passed
            else "prepared_physical_admission_failed",
            {
                "evidence_id": physical_admission.evidence_id,
                "admission_status": physical_admission.admission_status,
                "input_tokens": physical_admission.input_tokens,
                "max_input_tokens": physical_admission.max_input_tokens,
                "profile_revision": physical_admission.physical_profile_revision,
            },
        )


__all__ = [
    "ContextAggregateGateResult",
    "ContextAggregateVerificationResult",
    "ContextAggregateVerifier",
    "ContextPhysicalAdmissionVerifier",
    "ContextPhysicalMaterialization",
]
