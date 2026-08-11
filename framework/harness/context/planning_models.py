from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from framework.harness.context.compaction_models import ContextCompactionPlan
from framework.harness.context.verified_common import (
    identity,
    non_negative_int,
    reject_fields,
    required_text,
    strict_payload,
    text_tuple,
)
from framework.harness.control_plane.errors import HarnessValidationError


CONTEXT_PHYSICAL_ADMISSION_EVIDENCE_SCHEMA_REVISION = (
    "newsroom.context-physical-admission-evidence/v1"
)
CONTEXT_COMPACTION_PLANNING_RESULT_SCHEMA_REVISION = (
    "newsroom.context-compaction-planning-result/v1"
)


class ContextCompactionPlanningStatus(StrEnum):
    PLAN_READY = "plan_ready"
    NO_COMPACTION_REQUIRED = "no_compaction_required"
    PROTECTED_CONTEXT_EXCEEDS_WINDOW = "protected_context_exceeds_window"
    NO_ALLOWED_COMPACTION = "no_allowed_compaction"
    ACTION_BUDGET_EXHAUSTED = "action_budget_exhausted"


@dataclass(frozen=True)
class ContextPhysicalAdmissionEvidence:
    source_snapshot_id: str
    source_snapshot_checksum: str
    prepared_fingerprint: str
    physical_profile_revision: str
    tokenizer_revision: str
    normalizer_revision: str
    materialization_revision: str
    admission_status: str
    admitted: bool
    input_tokens: int
    max_input_tokens: int
    fixed_input_tokens: int
    group_input_tokens: Mapping[str, int]
    schema_revision: str = CONTEXT_PHYSICAL_ADMISSION_EVIDENCE_SCHEMA_REVISION
    evidence_id: str | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source_snapshot_id",
            "source_snapshot_checksum",
            "prepared_fingerprint",
            "physical_profile_revision",
            "tokenizer_revision",
            "normalizer_revision",
            "materialization_revision",
            "admission_status",
            "schema_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        if not isinstance(self.admitted, bool):
            raise HarnessValidationError("admitted must be a boolean")
        if self.admitted != (self.admission_status == "admitted"):
            raise HarnessValidationError(
                "admitted must match the admitted admission_status"
            )
        for field_name in (
            "input_tokens",
            "max_input_tokens",
            "fixed_input_tokens",
        ):
            object.__setattr__(
                self,
                field_name,
                non_negative_int(getattr(self, field_name), field=field_name),
            )
        if not isinstance(self.group_input_tokens, Mapping):
            raise HarnessValidationError("group_input_tokens must be an object")
        group_counts: dict[str, int] = {}
        for raw_group_id, raw_count in self.group_input_tokens.items():
            group_id = required_text(raw_group_id, field="group_input_tokens.group_id")
            if group_id in group_counts:
                raise HarnessValidationError(
                    "group_input_tokens must contain unique group ids"
                )
            group_counts[group_id] = non_negative_int(
                raw_count,
                field=f"group_input_tokens.{group_id}",
            )
        if self.fixed_input_tokens + sum(group_counts.values()) != self.input_tokens:
            raise HarnessValidationError(
                "fixed and group input token counts must equal input_tokens"
            )
        object.__setattr__(
            self,
            "group_input_tokens",
            MappingProxyType(group_counts),
        )
        expected_id, checksum = identity(
            "context-physical-admission",
            self.identity_projection(),
        )
        if self.evidence_id is not None and self.evidence_id != expected_id:
            raise HarnessValidationError(
                "physical admission evidence_id does not match semantic identity"
            )
        if self.checksum is not None and self.checksum != checksum:
            raise HarnessValidationError(
                "physical admission checksum does not match semantic identity"
            )
        object.__setattr__(self, "evidence_id", expected_id)
        object.__setattr__(self, "checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_checksum": self.source_snapshot_checksum,
            "prepared_fingerprint": self.prepared_fingerprint,
            "physical_profile_revision": self.physical_profile_revision,
            "tokenizer_revision": self.tokenizer_revision,
            "normalizer_revision": self.normalizer_revision,
            "materialization_revision": self.materialization_revision,
            "admission_status": self.admission_status,
            "admitted": self.admitted,
            "input_tokens": self.input_tokens,
            "max_input_tokens": self.max_input_tokens,
            "fixed_input_tokens": self.fixed_input_tokens,
            "group_input_tokens": dict(sorted(self.group_input_tokens.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "evidence_id": self.evidence_id,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextPhysicalAdmissionEvidence:
        payload = strict_payload(value, model="ContextPhysicalAdmissionEvidence")
        result = cls(
            source_snapshot_id=payload.pop("source_snapshot_id"),
            source_snapshot_checksum=payload.pop("source_snapshot_checksum"),
            prepared_fingerprint=payload.pop("prepared_fingerprint"),
            physical_profile_revision=payload.pop("physical_profile_revision"),
            tokenizer_revision=payload.pop("tokenizer_revision"),
            normalizer_revision=payload.pop("normalizer_revision"),
            materialization_revision=payload.pop("materialization_revision"),
            admission_status=payload.pop("admission_status"),
            admitted=payload.pop("admitted"),
            input_tokens=payload.pop("input_tokens"),
            max_input_tokens=payload.pop("max_input_tokens"),
            fixed_input_tokens=payload.pop("fixed_input_tokens"),
            group_input_tokens=payload.pop("group_input_tokens"),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_PHYSICAL_ADMISSION_EVIDENCE_SCHEMA_REVISION,
            ),
            evidence_id=payload.pop("evidence_id", None),
            checksum=payload.pop("checksum", None),
        )
        reject_fields(payload, model="ContextPhysicalAdmissionEvidence")
        return result


@dataclass(frozen=True)
class ContextPlanningBudgetUsage:
    actions: int = 0
    summary_calls: int = 0
    replans: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    cost_usd: float = 0.0
    turns: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "actions",
            "summary_calls",
            "replans",
            "llm_calls",
            "input_tokens",
            "turns",
        ):
            object.__setattr__(
                self,
                field_name,
                non_negative_int(getattr(self, field_name), field=field_name),
            )
        if (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or float(self.cost_usd) < 0
        ):
            raise HarnessValidationError("cost_usd must be non-negative")
        object.__setattr__(self, "cost_usd", float(self.cost_usd))

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": self.actions,
            "summary_calls": self.summary_calls,
            "replans": self.replans,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "cost_usd": self.cost_usd,
            "turns": self.turns,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextPlanningBudgetUsage:
        payload = strict_payload(value, model="ContextPlanningBudgetUsage")
        result = cls(
            actions=payload.pop("actions", 0),
            summary_calls=payload.pop("summary_calls", 0),
            replans=payload.pop("replans", 0),
            llm_calls=payload.pop("llm_calls", 0),
            input_tokens=payload.pop("input_tokens", 0),
            cost_usd=payload.pop("cost_usd", 0.0),
            turns=payload.pop("turns", 0),
        )
        reject_fields(payload, model="ContextPlanningBudgetUsage")
        return result


@dataclass(frozen=True)
class ContextCompactionPlanningResult:
    status: ContextCompactionPlanningStatus | str
    source_snapshot_id: str
    source_snapshot_checksum: str
    admission_evidence_id: str
    protected_group_ids: tuple[str, ...]
    reason_code: str
    plan: ContextCompactionPlan | None = None
    schema_revision: str = CONTEXT_COMPACTION_PLANNING_RESULT_SCHEMA_REVISION
    result_id: str | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            ContextCompactionPlanningStatus(self.status),
        )
        for field_name in (
            "source_snapshot_id",
            "source_snapshot_checksum",
            "admission_evidence_id",
            "reason_code",
            "schema_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "protected_group_ids",
            text_tuple(self.protected_group_ids, field="protected_group_ids"),
        )
        if self.status is ContextCompactionPlanningStatus.PLAN_READY:
            if not isinstance(self.plan, ContextCompactionPlan):
                raise HarnessValidationError("plan_ready result requires a plan")
        elif self.plan is not None:
            raise HarnessValidationError("non-plan planning result must not contain a plan")
        expected_id, checksum = identity(
            "context-planning-result",
            self.identity_projection(),
        )
        if self.result_id is not None and self.result_id != expected_id:
            raise HarnessValidationError(
                "planning result_id does not match semantic identity"
            )
        if self.checksum is not None and self.checksum != checksum:
            raise HarnessValidationError(
                "planning checksum does not match semantic identity"
            )
        object.__setattr__(self, "result_id", expected_id)
        object.__setattr__(self, "checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "status": self.status.value,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_checksum": self.source_snapshot_checksum,
            "admission_evidence_id": self.admission_evidence_id,
            "protected_group_ids": list(self.protected_group_ids),
            "reason_code": self.reason_code,
            "plan": self.plan.identity_projection() if self.plan is not None else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "result_id": self.result_id,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextCompactionPlanningResult:
        payload = strict_payload(value, model="ContextCompactionPlanningResult")
        raw_plan = payload.pop("plan", None)
        result = cls(
            status=payload.pop("status"),
            source_snapshot_id=payload.pop("source_snapshot_id"),
            source_snapshot_checksum=payload.pop("source_snapshot_checksum"),
            admission_evidence_id=payload.pop("admission_evidence_id"),
            protected_group_ids=tuple(payload.pop("protected_group_ids", ())),
            reason_code=payload.pop("reason_code"),
            plan=(
                ContextCompactionPlan.from_dict(raw_plan)
                if raw_plan is not None
                else None
            ),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_COMPACTION_PLANNING_RESULT_SCHEMA_REVISION,
            ),
            result_id=payload.pop("result_id", None),
            checksum=payload.pop("checksum", None),
        )
        reject_fields(payload, model="ContextCompactionPlanningResult")
        return result


__all__ = [
    "CONTEXT_COMPACTION_PLANNING_RESULT_SCHEMA_REVISION",
    "CONTEXT_PHYSICAL_ADMISSION_EVIDENCE_SCHEMA_REVISION",
    "ContextCompactionPlanningResult",
    "ContextCompactionPlanningStatus",
    "ContextPhysicalAdmissionEvidence",
    "ContextPlanningBudgetUsage",
]
