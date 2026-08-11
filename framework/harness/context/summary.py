from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from framework.harness.artifacts import ArtifactRef
from framework.harness.context.compaction_models import (
    ContextCompactionAction,
    ContextCompactionActionResult,
    ContextCompactionActionType,
    ContextLossReport,
    ContextLossRisk,
)
from framework.harness.context.group_models import (
    ContextGroup,
    ContextGroupKind,
    ContextGroupMember,
    ContextGroupMemberKind,
    ContextProtectionReason,
    ContextReconstructionPolicy,
)
from framework.harness.context.compaction_models import ContextCompactionPolicy
from framework.harness.context.planning import _protected_group_ids
from framework.harness.context.summary_models import ContextSummaryCandidate
from framework.harness.context.verified_common import (
    frozen_mapping,
    non_negative_int,
    required_text,
    text_tuple,
)
from framework.harness.context.verified_records import ContextSemanticSnapshot
from framework.harness.control_plane.errors import HarnessValidationError


@runtime_checkable
class ContextSummaryArtifactPort(Protocol):
    def read_artifact(self, ref: str) -> Mapping[str, Any]:
        ...

    def resolve_artifact(self, ref: str) -> ArtifactRef:
        ...


@runtime_checkable
class ContextSummaryWorkerPort(Protocol):
    def generate(self, request: "ContextSummaryRequest") -> "ContextSummaryWorkerResult":
        ...


@dataclass(frozen=True)
class ContextSummaryRequest:
    source_snapshot_id: str
    source_snapshot_checksum: str
    task_binding_ref: str
    policy_revision: str
    target_group_ids: tuple[str, ...]
    protected_group_ids: tuple[str, ...]
    max_input_tokens: int
    max_cost_usd: float
    summary_call_index: int
    diagnostic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for field_name in (
            "source_snapshot_id",
            "source_snapshot_checksum",
            "task_binding_ref",
            "policy_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "target_group_ids",
            text_tuple(self.target_group_ids, field="target_group_ids", required=True),
        )
        object.__setattr__(
            self,
            "protected_group_ids",
            text_tuple(self.protected_group_ids, field="protected_group_ids"),
        )
        object.__setattr__(
            self,
            "max_input_tokens",
            non_negative_int(self.max_input_tokens, field="max_input_tokens"),
        )
        if (
            isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or float(self.max_cost_usd) < 0
        ):
            raise HarnessValidationError("max_cost_usd must be non-negative")
        object.__setattr__(self, "max_cost_usd", float(self.max_cost_usd))
        object.__setattr__(
            self,
            "summary_call_index",
            non_negative_int(self.summary_call_index, field="summary_call_index"),
        )
        object.__setattr__(
            self,
            "diagnostic_metadata",
            frozen_mapping(self.diagnostic_metadata, field="diagnostic_metadata"),
        )


@dataclass(frozen=True)
class ContextSummaryWorkerResult:
    candidate: ContextSummaryCandidate
    input_tokens: int
    cost_usd: float

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ContextSummaryCandidate):
            raise HarnessValidationError(
                "summary worker result candidate must be ContextSummaryCandidate"
            )
        object.__setattr__(
            self,
            "input_tokens",
            non_negative_int(self.input_tokens, field="input_tokens"),
        )
        if (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or float(self.cost_usd) < 0
        ):
            raise HarnessValidationError("summary cost_usd must be non-negative")
        object.__setattr__(self, "cost_usd", float(self.cost_usd))


@dataclass(frozen=True)
class ContextSummaryVerificationResult:
    accepted: bool
    reason_code: str
    candidate_id: str
    covered_group_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise HarnessValidationError("accepted must be a boolean")
        object.__setattr__(
            self,
            "reason_code",
            required_text(self.reason_code, field="reason_code"),
        )
        object.__setattr__(
            self,
            "candidate_id",
            required_text(self.candidate_id, field="candidate_id"),
        )
        object.__setattr__(
            self,
            "covered_group_ids",
            text_tuple(self.covered_group_ids, field="covered_group_ids"),
        )


class ContextSummaryCandidateVerifier:
    def verify(
        self,
        candidate: ContextSummaryCandidate | Mapping[str, Any],
        *,
        source_snapshot: ContextSemanticSnapshot,
        target_group_ids: tuple[str, ...],
        policy: ContextCompactionPolicy,
        artifact_port: ContextSummaryArtifactPort,
    ) -> ContextSummaryVerificationResult:
        if isinstance(candidate, Mapping):
            try:
                candidate = ContextSummaryCandidate.from_dict(candidate)
            except (KeyError, TypeError, ValueError) as exc:
                raise HarnessValidationError(
                    "summary candidate payload is not a supported structured candidate"
                ) from exc
        if not isinstance(candidate, ContextSummaryCandidate):
            raise HarnessValidationError(
                "candidate must be ContextSummaryCandidate or a strict mapping"
            )
        if not isinstance(artifact_port, ContextSummaryArtifactPort):
            raise HarnessValidationError(
                "artifact_port must resolve summary artifact checksums"
            )
        target_ids = text_tuple(target_group_ids, field="target_group_ids", required=True)
        if candidate.covered_group_ids != target_ids:
            raise HarnessValidationError(
                "summary candidate coverage must exactly match action targets"
            )
        groups_by_id = {group.group_id: group for group in source_snapshot.groups}
        unknown_groups = set(candidate.covered_group_ids).difference(groups_by_id)
        if unknown_groups:
            raise HarnessValidationError("summary candidate contains unknown groups")
        protected = set(_protected_group_ids(source_snapshot, policy))
        for group_id in protected.intersection(candidate.covered_group_ids):
            group = groups_by_id[group_id]
            if (
                group.group_kind is not ContextGroupKind.EVIDENCE
                or ContextGroupKind.EVIDENCE in policy.protected_group_kinds
                or set(group.protection_reasons).difference(
                    {ContextProtectionReason.REQUIRED_EVIDENCE}
                )
            ):
                raise HarnessValidationError("summary candidate targets protected groups")
        if candidate.loss_risk not in tuple(policy.allowed_loss_risks):
            raise HarnessValidationError("summary candidate loss risk is not policy allowed")
        self._verify_artifact(candidate.summary_artifact_ref, artifact_port)
        allowed_refs = self._allowed_refs(
            tuple(groups_by_id[group_id] for group_id in candidate.covered_group_ids)
        )
        if set(candidate.source_refs).difference(allowed_refs):
            raise HarnessValidationError("summary candidate contains unknown source refs")
        for claim in candidate.claims:
            if not set(claim.supporting_refs).issubset(allowed_refs):
                raise HarnessValidationError("summary claim contains unsupported refs")
            if not claim.supporting_refs:
                raise HarnessValidationError("summary claim has no supporting refs")
        if set(candidate.tool_outcome_refs).difference(allowed_refs):
            raise HarnessValidationError("summary candidate contains unknown tool outcomes")
        self._verify_evidence_coverage(
            candidate,
            tuple(groups_by_id[group_id] for group_id in candidate.covered_group_ids),
            allowed_refs,
        )
        return ContextSummaryVerificationResult(
            accepted=True,
            reason_code="summary_candidate_gates_passed",
            candidate_id=candidate.candidate_id,
            covered_group_ids=candidate.covered_group_ids,
        )

    @staticmethod
    def _verify_artifact(
        artifact_ref: str,
        artifact_port: ContextSummaryArtifactPort,
    ) -> None:
        if "#sha256=" not in artifact_ref:
            raise HarnessValidationError(
                "summary artifact ref must include a checksum fragment"
            )
        base_ref, checksum = artifact_ref.rsplit("#sha256=", 1)
        if not base_ref or not checksum:
            raise HarnessValidationError("summary artifact ref checksum is malformed")
        resolved = artifact_port.resolve_artifact(artifact_ref)
        if not isinstance(resolved, ArtifactRef):
            raise HarnessValidationError("summary artifact resolver returned invalid ref")
        if resolved.checksum.removeprefix("sha256:") != checksum:
            raise HarnessValidationError("summary artifact checksum does not match ref")
        artifact_port.read_artifact(base_ref)

    @staticmethod
    def _allowed_refs(groups: tuple[ContextGroup, ...]) -> set[str]:
        refs: set[str] = set()
        for group in groups:
            refs.update({group.group_id, group.identity_checksum})
            refs.update(group.source_refs)
            refs.update(group.required_citation_refs)
            if group.reconstruction_ref:
                refs.add(group.reconstruction_ref)
            for member in group.members:
                refs.add(member.member_id)
                refs.add(member.content_ref)
                refs.update(member.source_refs)
            refs.update(group.semantic_metadata.get("lineage_refs", ()))
            refs.update(group.semantic_metadata.get("conflict_refs", ()))
            refs.update(group.semantic_metadata.get("required_span_refs", ()))
        return {ref for ref in refs if isinstance(ref, str)}

    @staticmethod
    def _verify_evidence_coverage(
        candidate: ContextSummaryCandidate,
        groups: tuple[ContextGroup, ...],
        allowed_refs: set[str],
    ) -> None:
        candidate_refs = set(candidate.source_refs)
        for claim in candidate.claims:
            candidate_refs.update(claim.supporting_refs)
        for group in groups:
            if group.group_kind is ContextGroupKind.EVIDENCE:
                required = set(group.source_refs)
                required.update(group.required_citation_refs)
                required.update(group.semantic_metadata.get("required_span_refs", ()))
                required.update(group.semantic_metadata.get("conflict_refs", ()))
                if not required.issubset(candidate_refs):
                    raise HarnessValidationError(
                        "summary candidate omits required evidence or conflict refs"
                    )
            if group.group_kind is ContextGroupKind.TOOL_TRANSACTION:
                if group.tool_transaction_state.value != "completed":
                    raise HarnessValidationError(
                        "summary candidate cannot cover a non-completed tool transaction"
                    )


class ContextSummaryMaterializer:
    def apply(
        self,
        candidate: ContextSummaryCandidate,
        *,
        source_snapshot: ContextSemanticSnapshot,
        action: ContextCompactionAction,
        current_groups: tuple[ContextGroup, ...] | None = None,
    ) -> tuple[tuple[ContextGroup, ...], ContextCompactionActionResult]:
        if action.action_type is not ContextCompactionActionType.SUMMARIZE_GROUPS:
            raise HarnessValidationError(
                "summary materializer requires SUMMARIZE_GROUPS action"
            )
        target_ids = set(action.target_group_ids)
        active_groups = current_groups or source_snapshot.groups
        groups_by_id = {group.group_id: group for group in active_groups}
        if candidate.covered_group_ids != action.target_group_ids:
            raise HarnessValidationError("summary candidate coverage is stale")
        if target_ids.difference(groups_by_id):
            raise HarnessValidationError("summary candidate target group is stale")
        summary_group = ContextGroup(
            group_kind=ContextGroupKind.MEMORY_REFERENCE,
            members=(
                ContextGroupMember(
                    member_kind=ContextGroupMemberKind.REFERENCE,
                    content_ref=candidate.summary_artifact_ref,
                    ordinal=0,
                    source_refs=candidate.source_refs,
                    semantic_metadata={
                        "candidate_id": candidate.candidate_id,
                        "covered_group_ids": candidate.covered_group_ids,
                        "claim_ids": tuple(claim.claim_id for claim in candidate.claims),
                    },
                ),
            ),
            source_refs=candidate.source_refs,
            reconstruction_policy=(
                # The artifact checksum is the durable reconstruction ref.
                # Promotion still waits for aggregate VERIFY.
                ContextReconstructionPolicy.DURABLE_REF
            ),
            reconstruction_ref=candidate.summary_artifact_ref,
            semantic_metadata={
                "candidate_id": candidate.candidate_id,
                "covered_group_ids": candidate.covered_group_ids,
                "omitted_topics": candidate.omitted_topics,
                "unresolved_questions": candidate.unresolved_questions,
                "tool_outcome_refs": candidate.tool_outcome_refs,
                "loss_risk": candidate.loss_risk.value,
            },
        )
        result_groups: list[ContextGroup] = []
        inserted = False
        for group in active_groups:
            if group.group_id in target_ids:
                if not inserted:
                    result_groups.append(summary_group)
                    inserted = True
                continue
            result_groups.append(group)
        if not inserted:
            raise HarnessValidationError("summary action has no active target groups")
        action_result = ContextCompactionActionResult(
            action=action,
            source_snapshot_id=source_snapshot.snapshot_id,
            result_group_ids=tuple(group.group_id for group in result_groups),
            summary_candidate_ref=candidate.summary_artifact_ref,
            loss_report=ContextLossReport(
                omitted_topics=candidate.omitted_topics,
                unresolved_questions=candidate.unresolved_questions,
                loss_risk=candidate.loss_risk,
            ),
            reason_code="verified_summary_candidate_materialized",
        )
        return tuple(result_groups), action_result


__all__ = [
    "ContextSummaryArtifactPort",
    "ContextSummaryCandidateVerifier",
    "ContextSummaryMaterializer",
    "ContextSummaryRequest",
    "ContextSummaryVerificationResult",
    "ContextSummaryWorkerPort",
    "ContextSummaryWorkerResult",
]
