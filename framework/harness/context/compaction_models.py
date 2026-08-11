from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from framework.harness.context.group_models import (
    ContextGroupKind,
    ContextProtectionReason,
)
from framework.harness.context.verified_common import (
    frozen_mapping,
    identity,
    non_negative_int,
    positive_int,
    reject_fields,
    required_text,
    strict_payload,
    text_tuple,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


CONTEXT_COMPACTION_POLICY_SCHEMA_REVISION = "newsroom.context-compaction-policy/v1"
CONTEXT_COMPACTION_PLAN_SCHEMA_REVISION = "newsroom.context-compaction-plan/v1"
CONTEXT_COMPACTION_ACTION_SCHEMA_REVISION = "newsroom.context-compaction-action/v1"


class ContextCompactionActionType(StrEnum):
    DROP_RECONSTRUCTABLE_GROUP = "drop_reconstructable_group"
    REPLACE_WITH_REFERENCE = "replace_with_reference"
    REDUCE_AUTHORIZED_TOOL_SET = "reduce_authorized_tool_set"
    SELECT_EVIDENCE_SPANS = "select_evidence_spans"
    COMPACT_OLD_CONVERSATION = "compact_old_conversation"
    SUMMARIZE_GROUPS = "summarize_groups"


REVERSIBLE_CONTEXT_ACTIONS = frozenset(
    {
        ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,
        ContextCompactionActionType.REPLACE_WITH_REFERENCE,
        ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET,
    }
)


class ContextCompactionOutcome(StrEnum):
    VERIFIED = "verified"
    NO_COMPACTION_REQUIRED = "no_compaction_required"
    PROTECTED_CONTEXT_EXCEEDS_WINDOW = "protected_context_exceeds_window"
    NO_ALLOWED_COMPACTION = "no_allowed_compaction"
    ACTION_BUDGET_EXHAUSTED = "action_budget_exhausted"
    SUMMARY_REJECTED = "summary_rejected"
    POST_COMPACTION_VERIFY_FAILED = "post_compaction_verify_failed"


class ContextLossRisk(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContextCompactionPolicy:
    policy_revision: str
    action_order: tuple[ContextCompactionActionType | str, ...]
    max_actions: int
    max_summary_calls: int
    max_replans: int
    max_llm_calls: int
    max_input_tokens: int
    max_cost_usd: float
    max_turns: int
    keep_recent_complete_turns: int = 4
    protected_group_kinds: tuple[ContextGroupKind | str, ...] = ()
    protected_reasons: tuple[ContextProtectionReason | str, ...] = ()
    allowed_loss_risks: tuple[ContextLossRisk | str, ...] = (
        ContextLossRisk.NONE,
        ContextLossRisk.LOW,
    )
    failure_policy: str = "halt"
    schema_revision: str = CONTEXT_COMPACTION_POLICY_SCHEMA_REVISION
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_revision",
            required_text(self.policy_revision, field="policy_revision"),
        )
        try:
            actions = tuple(ContextCompactionActionType(action) for action in self.action_order)
        except ValueError as exc:
            raise HarnessValidationError("unsupported compaction action") from exc
        if not actions or len(set(actions)) != len(actions):
            raise HarnessValidationError("action_order must be non-empty and unique")
        object.__setattr__(self, "action_order", actions)
        object.__setattr__(self, "max_actions", positive_int(self.max_actions, field="max_actions"))
        for field_name in (
            "max_summary_calls",
            "max_replans",
            "max_llm_calls",
            "max_input_tokens",
            "max_turns",
            "keep_recent_complete_turns",
        ):
            object.__setattr__(
                self,
                field_name,
                non_negative_int(getattr(self, field_name), field=field_name),
            )
        if self.max_input_tokens < 1:
            raise HarnessValidationError("max_input_tokens must be a positive integer")
        if self.max_turns < 1:
            raise HarnessValidationError("max_turns must be a positive integer")
        if (
            isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or float(self.max_cost_usd) < 0
        ):
            raise HarnessValidationError("max_cost_usd must be non-negative")
        object.__setattr__(self, "max_cost_usd", float(self.max_cost_usd))
        try:
            protected_kinds = tuple(ContextGroupKind(kind) for kind in self.protected_group_kinds)
            protected_reasons = tuple(
                ContextProtectionReason(reason) for reason in self.protected_reasons
            )
            loss_risks = tuple(ContextLossRisk(risk) for risk in self.allowed_loss_risks)
        except ValueError as exc:
            raise HarnessValidationError("unsupported compaction policy enum value") from exc
        for field_name, values in (
            ("protected_group_kinds", protected_kinds),
            ("protected_reasons", protected_reasons),
            ("allowed_loss_risks", loss_risks),
        ):
            if len(set(values)) != len(values):
                raise HarnessValidationError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, values)
        object.__setattr__(
            self,
            "failure_policy",
            required_text(self.failure_policy, field="failure_policy"),
        )
        if self.failure_policy not in {"halt", "fallback", "replan"}:
            raise HarnessValidationError("failure_policy must be halt, fallback, or replan")
        object.__setattr__(
            self,
            "schema_revision",
            required_text(self.schema_revision, field="schema_revision"),
        )
        object.__setattr__(self, "metadata", frozen_mapping(self.metadata, field="metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_revision": self.policy_revision,
            "action_order": [action.value for action in self.action_order],
            "max_actions": self.max_actions,
            "max_summary_calls": self.max_summary_calls,
            "max_replans": self.max_replans,
            "max_llm_calls": self.max_llm_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_turns": self.max_turns,
            "keep_recent_complete_turns": self.keep_recent_complete_turns,
            "protected_group_kinds": [kind.value for kind in self.protected_group_kinds],
            "protected_reasons": [reason.value for reason in self.protected_reasons],
            "allowed_loss_risks": [risk.value for risk in self.allowed_loss_risks],
            "failure_policy": self.failure_policy,
            "schema_revision": self.schema_revision,
            "metadata": to_jsonable(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextCompactionPolicy:
        payload = strict_payload(value, model="ContextCompactionPolicy")
        result = cls(
            policy_revision=payload.pop("policy_revision"),
            action_order=tuple(payload.pop("action_order")),
            max_actions=payload.pop("max_actions"),
            max_summary_calls=payload.pop("max_summary_calls"),
            max_replans=payload.pop("max_replans"),
            max_llm_calls=payload.pop("max_llm_calls"),
            max_input_tokens=payload.pop("max_input_tokens"),
            max_cost_usd=payload.pop("max_cost_usd"),
            max_turns=payload.pop("max_turns"),
            keep_recent_complete_turns=payload.pop("keep_recent_complete_turns", 4),
            protected_group_kinds=tuple(payload.pop("protected_group_kinds", ())),
            protected_reasons=tuple(payload.pop("protected_reasons", ())),
            allowed_loss_risks=tuple(
                payload.pop("allowed_loss_risks", (ContextLossRisk.NONE, ContextLossRisk.LOW))
            ),
            failure_policy=payload.pop("failure_policy", "halt"),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_COMPACTION_POLICY_SCHEMA_REVISION,
            ),
            metadata=payload.pop("metadata", {}),
        )
        reject_fields(payload, model="ContextCompactionPolicy")
        return result


@dataclass(frozen=True)
class ContextCompactionAction:
    action_type: ContextCompactionActionType | str
    target_group_ids: tuple[str, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict, repr=False)
    schema_revision: str = CONTEXT_COMPACTION_ACTION_SCHEMA_REVISION
    action_id: str | None = None
    identity_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_type", ContextCompactionActionType(self.action_type))
        object.__setattr__(
            self,
            "target_group_ids",
            text_tuple(
                self.target_group_ids,
                field="target_group_ids",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "parameters",
            frozen_mapping(self.parameters, field="parameters"),
        )
        object.__setattr__(
            self,
            "schema_revision",
            required_text(self.schema_revision, field="schema_revision"),
        )
        expected_id, checksum = identity("context-action", self.identity_projection())
        if self.action_id is not None and self.action_id != expected_id:
            raise HarnessValidationError("action_id does not match action semantic identity")
        if self.identity_checksum is not None and self.identity_checksum != checksum:
            raise HarnessValidationError("action identity checksum is invalid")
        object.__setattr__(self, "action_id", expected_id)
        object.__setattr__(self, "identity_checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "action_type": self.action_type.value,
            "target_group_ids": list(self.target_group_ids),
            "parameters": to_jsonable(dict(self.parameters)),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "action_id": self.action_id,
            "identity_checksum": self.identity_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextCompactionAction:
        payload = strict_payload(value, model="ContextCompactionAction")
        result = cls(
            action_type=payload.pop("action_type"),
            target_group_ids=tuple(payload.pop("target_group_ids")),
            parameters=payload.pop("parameters", {}),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_COMPACTION_ACTION_SCHEMA_REVISION,
            ),
            action_id=payload.pop("action_id", None),
            identity_checksum=payload.pop("identity_checksum", None),
        )
        reject_fields(payload, model="ContextCompactionAction")
        return result


@dataclass(frozen=True)
class ContextCompactionPlan:
    source_snapshot_id: str
    source_snapshot_checksum: str
    task_binding_ref: str
    target_input_tokens: int
    max_actions: int
    max_summary_calls: int
    max_replans: int
    actions: tuple[ContextCompactionAction, ...]
    protected_group_ids: tuple[str, ...]
    policy_revision: str
    physical_profile_revision: str
    schema_revision: str = CONTEXT_COMPACTION_PLAN_SCHEMA_REVISION
    plan_id: str | None = None
    identity_checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source_snapshot_id",
            "source_snapshot_checksum",
            "task_binding_ref",
            "policy_revision",
            "physical_profile_revision",
            "schema_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "target_input_tokens",
            positive_int(self.target_input_tokens, field="target_input_tokens"),
        )
        object.__setattr__(self, "max_actions", positive_int(self.max_actions, field="max_actions"))
        object.__setattr__(
            self,
            "max_summary_calls",
            non_negative_int(self.max_summary_calls, field="max_summary_calls"),
        )
        object.__setattr__(
            self,
            "max_replans",
            non_negative_int(self.max_replans, field="max_replans"),
        )
        actions = tuple(self.actions)
        if not all(isinstance(action, ContextCompactionAction) for action in actions):
            raise HarnessValidationError("actions must contain ContextCompactionAction values")
        if len(actions) > self.max_actions:
            raise HarnessValidationError("plan actions exceed max_actions")
        if sum(
            action.action_type is ContextCompactionActionType.SUMMARIZE_GROUPS
            for action in actions
        ) > self.max_summary_calls:
            raise HarnessValidationError("plan summary actions exceed max_summary_calls")
        object.__setattr__(self, "actions", actions)
        object.__setattr__(
            self,
            "protected_group_ids",
            text_tuple(self.protected_group_ids, field="protected_group_ids"),
        )
        expected_id, checksum = identity("context-plan", self.identity_projection())
        if self.plan_id is not None and self.plan_id != expected_id:
            raise HarnessValidationError("plan_id does not match plan semantic identity")
        if self.identity_checksum is not None and self.identity_checksum != checksum:
            raise HarnessValidationError("plan identity checksum is invalid")
        object.__setattr__(self, "plan_id", expected_id)
        object.__setattr__(self, "identity_checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_checksum": self.source_snapshot_checksum,
            "task_binding_ref": self.task_binding_ref,
            "target_input_tokens": self.target_input_tokens,
            "max_actions": self.max_actions,
            "max_summary_calls": self.max_summary_calls,
            "max_replans": self.max_replans,
            "actions": [action.identity_projection() for action in self.actions],
            "protected_group_ids": list(self.protected_group_ids),
            "policy_revision": self.policy_revision,
            "physical_profile_revision": self.physical_profile_revision,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "actions": [action.to_dict() for action in self.actions],
            "plan_id": self.plan_id,
            "identity_checksum": self.identity_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextCompactionPlan:
        payload = strict_payload(value, model="ContextCompactionPlan")
        raw_actions = payload.pop("actions")
        if not isinstance(raw_actions, (list, tuple)):
            raise HarnessValidationError("ContextCompactionPlan.actions must be a list")
        result = cls(
            source_snapshot_id=payload.pop("source_snapshot_id"),
            source_snapshot_checksum=payload.pop("source_snapshot_checksum"),
            task_binding_ref=payload.pop("task_binding_ref"),
            target_input_tokens=payload.pop("target_input_tokens"),
            max_actions=payload.pop("max_actions"),
            max_summary_calls=payload.pop("max_summary_calls"),
            max_replans=payload.pop("max_replans"),
            actions=tuple(ContextCompactionAction.from_dict(action) for action in raw_actions),
            protected_group_ids=tuple(payload.pop("protected_group_ids", ())),
            policy_revision=payload.pop("policy_revision"),
            physical_profile_revision=payload.pop("physical_profile_revision"),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_COMPACTION_PLAN_SCHEMA_REVISION,
            ),
            plan_id=payload.pop("plan_id", None),
            identity_checksum=payload.pop("identity_checksum", None),
        )
        reject_fields(payload, model="ContextCompactionPlan")
        return result


@dataclass(frozen=True)
class ContextLossReport:
    removed_group_ids: tuple[str, ...] = ()
    replaced_group_ids: tuple[str, ...] = ()
    omitted_span_refs: tuple[str, ...] = ()
    omitted_topics: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    loss_risk: ContextLossRisk | str = ContextLossRisk.NONE

    def __post_init__(self) -> None:
        for field_name in (
            "removed_group_ids",
            "replaced_group_ids",
            "omitted_span_refs",
            "omitted_topics",
            "unresolved_questions",
        ):
            object.__setattr__(
                self,
                field_name,
                text_tuple(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(self, "loss_risk", ContextLossRisk(self.loss_risk))

    def to_dict(self) -> dict[str, Any]:
        return {
            "removed_group_ids": list(self.removed_group_ids),
            "replaced_group_ids": list(self.replaced_group_ids),
            "omitted_span_refs": list(self.omitted_span_refs),
            "omitted_topics": list(self.omitted_topics),
            "unresolved_questions": list(self.unresolved_questions),
            "loss_risk": self.loss_risk.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextLossReport:
        payload = strict_payload(value, model="ContextLossReport")
        result = cls(
            removed_group_ids=tuple(payload.pop("removed_group_ids", ())),
            replaced_group_ids=tuple(payload.pop("replaced_group_ids", ())),
            omitted_span_refs=tuple(payload.pop("omitted_span_refs", ())),
            omitted_topics=tuple(payload.pop("omitted_topics", ())),
            unresolved_questions=tuple(payload.pop("unresolved_questions", ())),
            loss_risk=payload.pop("loss_risk", ContextLossRisk.NONE),
        )
        reject_fields(payload, model="ContextLossReport")
        return result


@dataclass(frozen=True)
class ContextCompactionActionResult:
    action: ContextCompactionAction
    source_snapshot_id: str
    result_group_ids: tuple[str, ...]
    reconstruction_refs: tuple[str, ...] = ()
    summary_candidate_ref: str | None = None
    loss_report: ContextLossReport = field(default_factory=ContextLossReport)
    applied: bool = True
    reason_code: str = "action_applied"

    def __post_init__(self) -> None:
        if not isinstance(self.action, ContextCompactionAction):
            raise HarnessValidationError("action must be ContextCompactionAction")
        object.__setattr__(
            self,
            "source_snapshot_id",
            required_text(self.source_snapshot_id, field="source_snapshot_id"),
        )
        object.__setattr__(
            self,
            "result_group_ids",
            text_tuple(self.result_group_ids, field="result_group_ids"),
        )
        object.__setattr__(
            self,
            "reconstruction_refs",
            text_tuple(self.reconstruction_refs, field="reconstruction_refs"),
        )
        if self.summary_candidate_ref is not None:
            object.__setattr__(
                self,
                "summary_candidate_ref",
                required_text(self.summary_candidate_ref, field="summary_candidate_ref"),
            )
        if not isinstance(self.loss_report, ContextLossReport):
            raise HarnessValidationError("loss_report must be ContextLossReport")
        if not isinstance(self.applied, bool):
            raise HarnessValidationError("applied must be a boolean")
        object.__setattr__(
            self,
            "reason_code",
            required_text(self.reason_code, field="reason_code"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "source_snapshot_id": self.source_snapshot_id,
            "result_group_ids": list(self.result_group_ids),
            "reconstruction_refs": list(self.reconstruction_refs),
            "summary_candidate_ref": self.summary_candidate_ref,
            "loss_report": self.loss_report.to_dict(),
            "applied": self.applied,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextCompactionActionResult:
        payload = strict_payload(value, model="ContextCompactionActionResult")
        result = cls(
            action=ContextCompactionAction.from_dict(payload.pop("action")),
            source_snapshot_id=payload.pop("source_snapshot_id"),
            result_group_ids=tuple(payload.pop("result_group_ids", ())),
            reconstruction_refs=tuple(payload.pop("reconstruction_refs", ())),
            summary_candidate_ref=payload.pop("summary_candidate_ref", None),
            loss_report=ContextLossReport.from_dict(payload.pop("loss_report", {})),
            applied=payload.pop("applied", True),
            reason_code=payload.pop("reason_code", "action_applied"),
        )
        reject_fields(payload, model="ContextCompactionActionResult")
        return result


__all__ = [
    "CONTEXT_COMPACTION_ACTION_SCHEMA_REVISION",
    "CONTEXT_COMPACTION_PLAN_SCHEMA_REVISION",
    "CONTEXT_COMPACTION_POLICY_SCHEMA_REVISION",
    "REVERSIBLE_CONTEXT_ACTIONS",
    "ContextCompactionAction",
    "ContextCompactionActionResult",
    "ContextCompactionActionType",
    "ContextCompactionOutcome",
    "ContextCompactionPlan",
    "ContextCompactionPolicy",
    "ContextLossReport",
    "ContextLossRisk",
]
