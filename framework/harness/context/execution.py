from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from framework.harness.artifacts import ArtifactPort, ArtifactRef, ArtifactWriteRequest
from framework.harness.context.compaction_models import (
    ContextCompactionAction,
    ContextCompactionActionResult,
    ContextCompactionActionType,
    ContextCompactionOutcome,
    ContextCompactionPlan,
    ContextCompactionPolicy,
    ContextLossReport,
    ContextLossRisk,
)
from framework.harness.context.group_models import (
    ContextGroup,
    ContextGroupKind,
    ContextGroupMember,
    ContextGroupMemberKind,
    ContextReconstructionPolicy,
    ContextToolTransactionState,
)
from framework.harness.context.planning import (
    ContextCompactionActionRegistry,
    ContextCompactionPlanValidator,
)
from framework.harness.context.planning_models import (
    ContextPhysicalAdmissionEvidence,
    ContextPlanningBudgetUsage,
)
from framework.harness.context.summary import (
    ContextSummaryArtifactPort,
    ContextSummaryCandidateVerifier,
    ContextSummaryMaterializer,
    ContextSummaryRequest,
    ContextSummaryWorkerPort,
    ContextSummaryWorkerResult,
)
from framework.harness.context.verified_records import (
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
)
from framework.harness.control_plane.errors import HarnessValidationError


class ContextCompactionExecutionStatus(StrEnum):
    APPLIED = "applied"
    ACTION_BUDGET_EXHAUSTED = "action_budget_exhausted"
    SUMMARY_REJECTED = "summary_rejected"
    COST_BUDGET_EXHAUSTED = "cost_budget_exhausted"
    TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"


@dataclass(frozen=True)
class ContextCompactionExecutionResult:
    status: ContextCompactionExecutionStatus | str
    source_snapshot_id: str
    source_snapshot_checksum: str
    result_snapshot: ContextSemanticSnapshot | None
    action_results: tuple[ContextCompactionActionResult, ...]
    usage: ContextPlanningBudgetUsage
    reconstruction_refs: tuple[str, ...] = ()
    summary_refs: tuple[str, ...] = ()
    outcome: ContextCompactionOutcome | None = None
    reason_code: str = "actions_applied_pending_verify"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            ContextCompactionExecutionStatus(self.status),
        )
        if not isinstance(self.source_snapshot_id, str) or not self.source_snapshot_id:
            raise HarnessValidationError("source_snapshot_id is required")
        if not isinstance(self.source_snapshot_checksum, str) or not self.source_snapshot_checksum:
            raise HarnessValidationError("source_snapshot_checksum is required")
        if self.result_snapshot is not None and not isinstance(
            self.result_snapshot,
            ContextSemanticSnapshot,
        ):
            raise HarnessValidationError(
                "result_snapshot must be ContextSemanticSnapshot or None"
            )
        if self.result_snapshot is not None and self.result_snapshot.snapshot_kind is not ContextSemanticSnapshotKind.RESULT:
            raise HarnessValidationError("execution result snapshot must be a result snapshot")
        action_results = tuple(self.action_results)
        if not all(
            isinstance(result, ContextCompactionActionResult)
            for result in action_results
        ):
            raise HarnessValidationError(
                "action_results must contain ContextCompactionActionResult values"
            )
        object.__setattr__(self, "action_results", action_results)
        if not isinstance(self.usage, ContextPlanningBudgetUsage):
            raise HarnessValidationError("usage must be ContextPlanningBudgetUsage")
        if self.status is ContextCompactionExecutionStatus.APPLIED:
            if self.result_snapshot is None:
                raise HarnessValidationError("applied execution requires a result snapshot")
            if self.outcome is not None:
                raise HarnessValidationError("applied execution must await aggregate VERIFY")
        elif self.result_snapshot is not None:
            raise HarnessValidationError("halted execution must not activate a result snapshot")
        if self.outcome is not None:
            object.__setattr__(self, "outcome", ContextCompactionOutcome(self.outcome))
        object.__setattr__(self, "reconstruction_refs", tuple(self.reconstruction_refs))
        object.__setattr__(self, "summary_refs", tuple(self.summary_refs))
        object.__setattr__(self, "reason_code", str(self.reason_code))


class ContextCompactionActionExecutor:
    def __init__(
        self,
        artifact_port: ArtifactPort,
        *,
        registry: ContextCompactionActionRegistry | None = None,
        summary_worker: ContextSummaryWorkerPort | None = None,
        summary_artifact_port: ContextSummaryArtifactPort | None = None,
    ) -> None:
        if not isinstance(artifact_port, ArtifactPort):
            raise HarnessValidationError("artifact_port must implement ArtifactPort")
        self._artifact_port = artifact_port
        self._registry = registry or ContextCompactionActionRegistry.standard()
        self._validator = ContextCompactionPlanValidator(self._registry)
        if summary_worker is not None and not isinstance(
            summary_worker,
            ContextSummaryWorkerPort,
        ):
            raise HarnessValidationError(
                "summary_worker must implement ContextSummaryWorkerPort"
            )
        if summary_artifact_port is not None and not isinstance(
            summary_artifact_port,
            ContextSummaryArtifactPort,
        ):
            raise HarnessValidationError(
                "summary_artifact_port must resolve summary artifact checksums"
            )
        self._summary_worker = summary_worker
        self._summary_artifact_port = summary_artifact_port
        self._summary_verifier = ContextSummaryCandidateVerifier()
        self._summary_materializer = ContextSummaryMaterializer()

    def execute(
        self,
        plan: ContextCompactionPlan,
        *,
        source_snapshot: ContextSemanticSnapshot,
        initial_admission: ContextPhysicalAdmissionEvidence,
        policy: ContextCompactionPolicy,
        budget_usage: ContextPlanningBudgetUsage | None = None,
    ) -> ContextCompactionExecutionResult:
        usage = budget_usage or ContextPlanningBudgetUsage()
        self._validator.validate(
            plan,
            source_snapshot=source_snapshot,
            policy=policy,
            initial_admission=initial_admission,
            budget_usage=usage,
        )
        current_groups = list(source_snapshot.groups)
        action_results: list[ContextCompactionActionResult] = []
        reconstruction_refs: list[str] = []
        summary_refs: list[str] = []
        current_usage = usage
        for action in plan.actions:
            if current_usage.actions >= plan.max_actions:
                return self._halt(
                    status=ContextCompactionExecutionStatus.ACTION_BUDGET_EXHAUSTED,
                    source_snapshot=source_snapshot,
                    action_results=action_results,
                    usage=current_usage,
                    reason_code="action_budget_exhausted_during_execution",
                )
            if current_usage.turns >= plan.max_turns:
                return self._halt(
                    status=ContextCompactionExecutionStatus.TURN_BUDGET_EXHAUSTED,
                    source_snapshot=source_snapshot,
                    action_results=action_results,
                    usage=current_usage,
                    reason_code="turn_budget_exhausted_during_execution",
                )
            if action.action_type is ContextCompactionActionType.SUMMARIZE_GROUPS:
                if self._summary_worker is None or self._summary_artifact_port is None:
                    return self._halt(
                        status=ContextCompactionExecutionStatus.SUMMARY_REJECTED,
                        source_snapshot=source_snapshot,
                        action_results=action_results,
                        usage=current_usage,
                        reason_code="summary_worker_not_injected",
                    )
                summary_result = self._execute_summary_action(
                    action,
                    current_groups=tuple(current_groups),
                    source_snapshot=source_snapshot,
                    policy=policy,
                    plan=plan,
                    usage=current_usage,
                    action_results=action_results,
                )
                if isinstance(summary_result, ContextCompactionExecutionResult):
                    return summary_result
                current_groups, action_result, current_usage = summary_result
                action_results.append(action_result)
                summary_refs.append(action_result.summary_candidate_ref or "")
                continue
            current_groups, action_result = self._apply_action(
                action,
                current_groups=tuple(current_groups),
                source_snapshot=source_snapshot,
            )
            action_results.append(action_result)
            reconstruction_refs.extend(action_result.reconstruction_refs)
            current_usage = ContextPlanningBudgetUsage(
                actions=current_usage.actions + 1,
                summary_calls=current_usage.summary_calls,
                replans=current_usage.replans,
                llm_calls=current_usage.llm_calls,
                input_tokens=current_usage.input_tokens,
                cost_usd=current_usage.cost_usd,
                turns=current_usage.turns + 1,
            )
        result_snapshot = ContextSemanticSnapshot(
            run_id=source_snapshot.run_id,
            stage_id=source_snapshot.stage_id,
            task_binding_ref=source_snapshot.task_binding_ref,
            groups=tuple(current_groups),
            policy_revision=source_snapshot.policy_revision,
            physical_profile_revision=source_snapshot.physical_profile_revision,
            snapshot_kind=ContextSemanticSnapshotKind.RESULT,
            parent_snapshot_id=source_snapshot.snapshot_id,
        )
        return ContextCompactionExecutionResult(
            status=ContextCompactionExecutionStatus.APPLIED,
            source_snapshot_id=source_snapshot.snapshot_id,
            source_snapshot_checksum=source_snapshot.checksum,
            result_snapshot=result_snapshot,
            action_results=tuple(action_results),
            usage=current_usage,
            reconstruction_refs=tuple(reconstruction_refs),
            summary_refs=tuple(summary_refs),
        )

    def _execute_summary_action(
        self,
        action: ContextCompactionAction,
        *,
        current_groups: tuple[ContextGroup, ...],
        source_snapshot: ContextSemanticSnapshot,
        policy: ContextCompactionPolicy,
        plan: ContextCompactionPlan,
        usage: ContextPlanningBudgetUsage,
        action_results: list[ContextCompactionActionResult],
    ) -> tuple[
        tuple[ContextGroup, ...],
        ContextCompactionActionResult,
        ContextPlanningBudgetUsage,
    ] | ContextCompactionExecutionResult:
        if usage.summary_calls >= plan.max_summary_calls:
            return self._halt(
                status=ContextCompactionExecutionStatus.SUMMARY_REJECTED,
                source_snapshot=source_snapshot,
                action_results=action_results,
                usage=usage,
                reason_code="summary_call_budget_exhausted",
            )
        if usage.llm_calls >= plan.max_llm_calls:
            return self._halt(
                status=ContextCompactionExecutionStatus.SUMMARY_REJECTED,
                source_snapshot=source_snapshot,
                action_results=action_results,
                usage=usage,
                reason_code="summary_llm_budget_exhausted",
            )
        request = ContextSummaryRequest(
            source_snapshot_id=source_snapshot.snapshot_id,
            source_snapshot_checksum=source_snapshot.checksum,
            task_binding_ref=source_snapshot.task_binding_ref,
            policy_revision=policy.policy_revision,
            target_group_ids=action.target_group_ids,
            protected_group_ids=plan.protected_group_ids,
            max_input_tokens=plan.target_input_tokens,
            max_cost_usd=max(0.0, plan.max_cost_usd - usage.cost_usd),
            summary_call_index=usage.summary_calls,
        )
        worker_result = self._summary_worker.generate(request)
        if not isinstance(worker_result, ContextSummaryWorkerResult):
            return self._halt(
                status=ContextCompactionExecutionStatus.SUMMARY_REJECTED,
                source_snapshot=source_snapshot,
                action_results=action_results,
                usage=usage,
                reason_code="summary_worker_result_contract_invalid",
            )
        next_usage = ContextPlanningBudgetUsage(
            actions=usage.actions,
            summary_calls=usage.summary_calls + 1,
            replans=usage.replans,
            llm_calls=usage.llm_calls + 1,
            input_tokens=usage.input_tokens + worker_result.input_tokens,
            cost_usd=usage.cost_usd + worker_result.cost_usd,
            turns=usage.turns + 1,
        )
        if worker_result.input_tokens > plan.target_input_tokens:
            return self._halt(
                status=ContextCompactionExecutionStatus.SUMMARY_REJECTED,
                source_snapshot=source_snapshot,
                action_results=action_results,
                usage=next_usage,
                reason_code="summary_input_budget_exceeded",
            )
        if next_usage.cost_usd > plan.max_cost_usd:
            return self._halt(
                status=ContextCompactionExecutionStatus.COST_BUDGET_EXHAUSTED,
                source_snapshot=source_snapshot,
                action_results=action_results,
                usage=next_usage,
                reason_code="summary_cost_budget_exhausted",
            )
        try:
            self._summary_verifier.verify(
                worker_result.candidate,
                source_snapshot=source_snapshot,
                target_group_ids=action.target_group_ids,
                policy=policy,
                artifact_port=self._summary_artifact_port,
            )
            groups, action_result = self._summary_materializer.apply(
                worker_result.candidate,
                source_snapshot=source_snapshot,
                action=action,
                current_groups=current_groups,
            )
        except HarnessValidationError:
            return self._halt(
                status=ContextCompactionExecutionStatus.SUMMARY_REJECTED,
                source_snapshot=source_snapshot,
                action_results=action_results,
                usage=next_usage,
                reason_code="summary_candidate_rejected_by_deterministic_gates",
            )
        return groups, action_result, next_usage

    def _apply_action(
        self,
        action: ContextCompactionAction,
        *,
        current_groups: tuple[ContextGroup, ...],
        source_snapshot: ContextSemanticSnapshot,
    ) -> tuple[list[ContextGroup], ContextCompactionActionResult]:
        groups_by_id = {group.group_id: group for group in current_groups}
        targets = tuple(groups_by_id[group_id] for group_id in action.target_group_ids)
        target_ids = set(action.target_group_ids)
        if action.action_type is ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP:
            reconstruction_refs = tuple(
                group.reconstruction_ref for group in targets if group.reconstruction_ref
            )
            result_groups = [
                group for group in current_groups if group.group_id not in target_ids
            ]
            return result_groups, ContextCompactionActionResult(
                action=action,
                source_snapshot_id=source_snapshot.snapshot_id,
                result_group_ids=tuple(group.group_id for group in result_groups),
                reconstruction_refs=reconstruction_refs,
                loss_report=ContextLossReport(
                    removed_group_ids=tuple(action.target_group_ids),
                    loss_risk=ContextLossRisk.NONE,
                ),
                reason_code="reconstructable_groups_dropped",
            )
        if action.action_type is ContextCompactionActionType.REPLACE_WITH_REFERENCE:
            replacements: dict[str, ContextGroup] = {}
            refs: list[str] = []
            for group in targets:
                artifact_ref = self._write_reconstruction_ref(group)
                refs.append(artifact_ref)
                replacements[group.group_id] = _reference_group(group, artifact_ref)
            result_groups = [
                replacements.get(group.group_id, group) for group in current_groups
            ]
            return result_groups, ContextCompactionActionResult(
                action=action,
                source_snapshot_id=source_snapshot.snapshot_id,
                result_group_ids=tuple(group.group_id for group in result_groups),
                reconstruction_refs=tuple(refs),
                loss_report=ContextLossReport(
                    replaced_group_ids=tuple(action.target_group_ids),
                    loss_risk=ContextLossRisk.NONE,
                ),
                reason_code="groups_replaced_with_durable_refs",
            )
        if action.action_type is ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET:
            result_groups = [
                group for group in current_groups if group.group_id not in target_ids
            ]
            return result_groups, ContextCompactionActionResult(
                action=action,
                source_snapshot_id=source_snapshot.snapshot_id,
                result_group_ids=tuple(group.group_id for group in result_groups),
                loss_report=ContextLossReport(
                    removed_group_ids=tuple(action.target_group_ids),
                    loss_risk=ContextLossRisk.NONE,
                ),
                reason_code="unreachable_authorized_tools_reduced",
            )
        if action.action_type is ContextCompactionActionType.SELECT_EVIDENCE_SPANS:
            if len(targets) != 1:
                raise HarnessValidationError(
                    "evidence selection executor requires one target group"
                )
            selected = tuple(action.parameters["selected_span_refs"])
            selected_set = set(selected)
            original = targets[0]
            selected_members = tuple(
                member for member in original.members if member.content_ref in selected_set
            )
            semantic_metadata = dict(original.semantic_metadata)
            semantic_metadata["selected_span_refs"] = selected
            semantic_metadata["covered_group_ids"] = tuple(
                dict.fromkeys(
                    (
                        *tuple(semantic_metadata.get("covered_group_ids", ())),
                        original.group_id,
                    )
                )
            )
            replacement = ContextGroup(
                group_kind=original.group_kind,
                members=selected_members,
                source_refs=original.source_refs,
                protection_reasons=original.protection_reasons,
                reconstruction_policy=original.reconstruction_policy,
                reconstruction_ref=original.reconstruction_ref,
                query_binding_ref=original.query_binding_ref,
                required_citation_refs=original.required_citation_refs,
                semantic_metadata=semantic_metadata,
            )
            result_groups = [
                replacement if group.group_id == original.group_id else group
                for group in current_groups
            ]
            omitted = tuple(
                member.content_ref
                for member in original.members
                if member.content_ref not in selected_set
            )
            return result_groups, ContextCompactionActionResult(
                action=action,
                source_snapshot_id=source_snapshot.snapshot_id,
                result_group_ids=tuple(group.group_id for group in result_groups),
                loss_report=ContextLossReport(
                    omitted_span_refs=omitted,
                    loss_risk=ContextLossRisk.LOW,
                ),
                reason_code="evidence_spans_selected_extractively",
            )
        if action.action_type is ContextCompactionActionType.COMPACT_OLD_CONVERSATION:
            result_groups = [
                group for group in current_groups if group.group_id not in target_ids
            ]
            return result_groups, ContextCompactionActionResult(
                action=action,
                source_snapshot_id=source_snapshot.snapshot_id,
                result_group_ids=tuple(group.group_id for group in result_groups),
                loss_report=ContextLossReport(
                    removed_group_ids=tuple(action.target_group_ids),
                    loss_risk=ContextLossRisk.LOW,
                ),
                reason_code="old_complete_conversation_compacted",
            )
        raise HarnessValidationError(
            f"unsupported executable compaction action: {action.action_type.value}"
        )

    def _write_reconstruction_ref(self, group: ContextGroup) -> str:
        request = ArtifactWriteRequest(
            artifact_type="context-reconstruction-reference",
            payload={
                "source_group_id": group.group_id,
                "source_group_checksum": group.identity_checksum,
                "source_refs": list(group.source_refs),
                "reconstruction_policy": group.reconstruction_policy.value,
            },
            metadata={
                "source_group_id": group.group_id,
                "context_ref_only": True,
            },
        )
        artifact = self._artifact_port.write_artifact(request)
        if not isinstance(artifact, ArtifactRef):
            raise HarnessValidationError(
                "artifact port must return ArtifactRef for reconstruction references"
            )
        checksum = artifact.checksum.removeprefix("sha256:")
        if not checksum or not artifact.ref.strip():
            raise HarnessValidationError(
                "artifact ref must contain a real ref and checksum"
            )
        return f"{artifact.ref}#sha256={checksum}"

    @staticmethod
    def _halt(
        *,
        status: ContextCompactionExecutionStatus,
        source_snapshot: ContextSemanticSnapshot,
        action_results: list[ContextCompactionActionResult],
        usage: ContextPlanningBudgetUsage,
        reason_code: str,
    ) -> ContextCompactionExecutionResult:
        return ContextCompactionExecutionResult(
            status=status,
            source_snapshot_id=source_snapshot.snapshot_id,
            source_snapshot_checksum=source_snapshot.checksum,
            result_snapshot=None,
            action_results=tuple(action_results),
            usage=usage,
            outcome={
                ContextCompactionExecutionStatus.ACTION_BUDGET_EXHAUSTED: (
                    ContextCompactionOutcome.ACTION_BUDGET_EXHAUSTED
                ),
                ContextCompactionExecutionStatus.SUMMARY_REJECTED: (
                    ContextCompactionOutcome.SUMMARY_REJECTED
                ),
                ContextCompactionExecutionStatus.TURN_BUDGET_EXHAUSTED: (
                    ContextCompactionOutcome.ACTION_BUDGET_EXHAUSTED
                ),
            }.get(status),
            reason_code=reason_code,
        )


def _reference_group(group: ContextGroup, artifact_ref: str) -> ContextGroup:
    return ContextGroup(
        group_kind=ContextGroupKind.MEMORY_REFERENCE,
        members=(
            ContextGroupMember(
                member_kind=ContextGroupMemberKind.REFERENCE,
                content_ref=artifact_ref,
                ordinal=0,
                source_refs=group.source_refs,
                semantic_metadata={
                    "replaced_group_id": group.group_id,
                    "replaced_group_kind": group.group_kind.value,
                },
            ),
        ),
        source_refs=group.source_refs,
        reconstruction_policy=ContextReconstructionPolicy.DURABLE_REF,
        reconstruction_ref=artifact_ref,
        semantic_metadata={
            "replaced_group_id": group.group_id,
            "replaced_group_kind": group.group_kind.value,
            "artifact_ref": artifact_ref,
        },
    )


__all__ = [
    "ContextCompactionActionExecutor",
    "ContextCompactionExecutionResult",
    "ContextCompactionExecutionStatus",
]
