from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from framework.harness.context.compaction_models import (
    ContextCompactionActionResult,
    ContextCompactionOutcome,
    ContextLossReport,
)
from framework.harness.context.group_models import ContextGroup
from framework.harness.context.verified_common import (
    identity,
    mapping_tuple,
    non_negative_int,
    optional_text,
    reject_fields,
    required_text,
    strict_payload,
    text_tuple,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


CONTEXT_SEMANTIC_SNAPSHOT_SCHEMA_REVISION = "newsroom.context-semantic-snapshot/v1"
CONTEXT_COMPRESSION_RECORD_SCHEMA_REVISION = "newsroom.context-compression-record/v2"


class ContextSemanticSnapshotKind(StrEnum):
    SOURCE = "source"
    RESULT = "result"
    REJECTED_RESULT = "rejected_result"


@dataclass(frozen=True)
class ContextSemanticSnapshot:
    run_id: str
    task_binding_ref: str
    groups: tuple[ContextGroup, ...]
    policy_revision: str
    snapshot_kind: ContextSemanticSnapshotKind | str
    step_id: str | None = None
    physical_profile_revision: str | None = None
    parent_snapshot_id: str | None = None
    schema_revision: str = CONTEXT_SEMANTIC_SNAPSHOT_SCHEMA_REVISION
    snapshot_id: str | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("run_id", "task_binding_ref", "policy_revision", "schema_revision"):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(self, "step_id", optional_text(self.step_id, field="step_id"))
        object.__setattr__(
            self,
            "physical_profile_revision",
            optional_text(
                self.physical_profile_revision,
                field="physical_profile_revision",
            ),
        )
        object.__setattr__(
            self,
            "parent_snapshot_id",
            optional_text(self.parent_snapshot_id, field="parent_snapshot_id"),
        )
        groups = tuple(self.groups)
        if not groups or not all(isinstance(group, ContextGroup) for group in groups):
            raise HarnessValidationError(
                "groups must contain at least one ContextGroup"
            )
        group_ids = tuple(group.group_id for group in groups)
        if len(set(group_ids)) != len(group_ids):
            raise HarnessValidationError("snapshot groups must have unique identities")
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "snapshot_kind", ContextSemanticSnapshotKind(self.snapshot_kind))
        if (
            self.snapshot_kind is ContextSemanticSnapshotKind.SOURCE
            and self.parent_snapshot_id is not None
        ):
            raise HarnessValidationError("source snapshot must not have a parent snapshot")
        if (
            self.snapshot_kind is not ContextSemanticSnapshotKind.SOURCE
            and self.parent_snapshot_id is None
        ):
            raise HarnessValidationError("result snapshot requires parent_snapshot_id")
        expected_id, checksum = identity("context-snapshot-v2", self.identity_projection())
        if self.snapshot_id is not None and self.snapshot_id != expected_id:
            raise HarnessValidationError("snapshot_id does not match snapshot identity")
        if self.checksum is not None and self.checksum != checksum:
            raise HarnessValidationError("snapshot checksum does not match snapshot identity")
        object.__setattr__(self, "snapshot_id", expected_id)
        object.__setattr__(self, "checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "task_binding_ref": self.task_binding_ref,
            "groups": [group.identity_projection() for group in self.groups],
            "policy_revision": self.policy_revision,
            "physical_profile_revision": self.physical_profile_revision,
            "parent_snapshot_id": self.parent_snapshot_id,
            "snapshot_kind": self.snapshot_kind.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "groups": [group.to_dict() for group in self.groups],
            "snapshot_id": self.snapshot_id,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextSemanticSnapshot:
        payload = strict_payload(value, model="ContextSemanticSnapshot")
        raw_groups = payload.pop("groups")
        if not isinstance(raw_groups, (list, tuple)):
            raise HarnessValidationError("ContextSemanticSnapshot.groups must be a list")
        result = cls(
            run_id=payload.pop("run_id"),
            step_id=payload.pop("step_id", None),
            task_binding_ref=payload.pop("task_binding_ref"),
            groups=tuple(ContextGroup.from_dict(group) for group in raw_groups),
            policy_revision=payload.pop("policy_revision"),
            physical_profile_revision=payload.pop("physical_profile_revision", None),
            parent_snapshot_id=payload.pop("parent_snapshot_id", None),
            snapshot_kind=payload.pop("snapshot_kind"),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_SEMANTIC_SNAPSHOT_SCHEMA_REVISION,
            ),
            snapshot_id=payload.pop("snapshot_id", None),
            checksum=payload.pop("checksum", None),
        )
        reject_fields(payload, model="ContextSemanticSnapshot")
        return result


@dataclass(frozen=True)
class ContextCompressionRecordV2:
    run_id: str
    source_snapshot_id: str
    source_snapshot_checksum: str
    result_snapshot_id: str
    result_snapshot_checksum: str
    plan_id: str
    policy_revision: str
    action_results: tuple[ContextCompactionActionResult, ...]
    before_input_tokens: int
    after_input_tokens: int
    retained_group_ids: tuple[str, ...]
    removed_group_ids: tuple[str, ...]
    replaced_group_ids: tuple[str, ...]
    protected_group_ids: tuple[str, ...]
    reconstruction_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    summary_refs: tuple[str, ...]
    loss_report: ContextLossReport
    gate_results: tuple[dict[str, Any], ...]
    aggregate_verdict: ContextCompactionOutcome | str
    reason_code: str
    profile_revision: str
    tokenizer_revision: str
    normalizer_revision: str
    step_id: str | None = None
    schema_revision: str = CONTEXT_COMPRESSION_RECORD_SCHEMA_REVISION
    record_id: str | None = None
    checksum: str | None = None
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "source_snapshot_id",
            "source_snapshot_checksum",
            "result_snapshot_id",
            "result_snapshot_checksum",
            "plan_id",
            "policy_revision",
            "reason_code",
            "profile_revision",
            "tokenizer_revision",
            "normalizer_revision",
            "schema_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(self, "step_id", optional_text(self.step_id, field="step_id"))
        actions = tuple(self.action_results)
        if not all(isinstance(result, ContextCompactionActionResult) for result in actions):
            raise HarnessValidationError(
                "action_results must contain ContextCompactionActionResult values"
            )
        object.__setattr__(self, "action_results", actions)
        object.__setattr__(
            self,
            "before_input_tokens",
            non_negative_int(self.before_input_tokens, field="before_input_tokens"),
        )
        object.__setattr__(
            self,
            "after_input_tokens",
            non_negative_int(self.after_input_tokens, field="after_input_tokens"),
        )
        for field_name in (
            "retained_group_ids",
            "removed_group_ids",
            "replaced_group_ids",
            "protected_group_ids",
            "reconstruction_refs",
            "source_refs",
            "summary_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                text_tuple(getattr(self, field_name), field=field_name),
            )
        if not isinstance(self.loss_report, ContextLossReport):
            raise HarnessValidationError("loss_report must be ContextLossReport")
        object.__setattr__(
            self,
            "gate_results",
            mapping_tuple(self.gate_results, field="gate_results"),
        )
        object.__setattr__(
            self,
            "aggregate_verdict",
            ContextCompactionOutcome(self.aggregate_verdict),
        )
        expected_id, checksum = identity("context-compression-v2", self.identity_projection())
        if self.record_id is not None and self.record_id != expected_id:
            raise HarnessValidationError("record_id does not match record identity")
        if self.checksum is not None and self.checksum != checksum:
            raise HarnessValidationError("record checksum does not match record identity")
        object.__setattr__(self, "record_id", expected_id)
        object.__setattr__(self, "checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_checksum": self.source_snapshot_checksum,
            "result_snapshot_id": self.result_snapshot_id,
            "result_snapshot_checksum": self.result_snapshot_checksum,
            "plan_id": self.plan_id,
            "policy_revision": self.policy_revision,
            "action_results": [result.to_dict() for result in self.action_results],
            "before_input_tokens": self.before_input_tokens,
            "after_input_tokens": self.after_input_tokens,
            "retained_group_ids": list(self.retained_group_ids),
            "removed_group_ids": list(self.removed_group_ids),
            "replaced_group_ids": list(self.replaced_group_ids),
            "protected_group_ids": list(self.protected_group_ids),
            "reconstruction_refs": list(self.reconstruction_refs),
            "source_refs": list(self.source_refs),
            "summary_refs": list(self.summary_refs),
            "loss_report": self.loss_report.to_dict(),
            "gate_results": to_jsonable(list(self.gate_results)),
            "aggregate_verdict": self.aggregate_verdict.value,
            "reason_code": self.reason_code,
            "profile_revision": self.profile_revision,
            "tokenizer_revision": self.tokenizer_revision,
            "normalizer_revision": self.normalizer_revision,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "record_id": self.record_id,
            "checksum": self.checksum,
            "created_at": format_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextCompressionRecordV2:
        payload = strict_payload(value, model="ContextCompressionRecordV2")
        raw_actions = payload.pop("action_results", ())
        raw_gates = payload.pop("gate_results", ())
        result = cls(
            run_id=payload.pop("run_id"),
            step_id=payload.pop("step_id", None),
            source_snapshot_id=payload.pop("source_snapshot_id"),
            source_snapshot_checksum=payload.pop("source_snapshot_checksum"),
            result_snapshot_id=payload.pop("result_snapshot_id"),
            result_snapshot_checksum=payload.pop("result_snapshot_checksum"),
            plan_id=payload.pop("plan_id"),
            policy_revision=payload.pop("policy_revision"),
            action_results=tuple(
                ContextCompactionActionResult.from_dict(action) for action in raw_actions
            ),
            before_input_tokens=payload.pop("before_input_tokens"),
            after_input_tokens=payload.pop("after_input_tokens"),
            retained_group_ids=tuple(payload.pop("retained_group_ids", ())),
            removed_group_ids=tuple(payload.pop("removed_group_ids", ())),
            replaced_group_ids=tuple(payload.pop("replaced_group_ids", ())),
            protected_group_ids=tuple(payload.pop("protected_group_ids", ())),
            reconstruction_refs=tuple(payload.pop("reconstruction_refs", ())),
            source_refs=tuple(payload.pop("source_refs", ())),
            summary_refs=tuple(payload.pop("summary_refs", ())),
            loss_report=ContextLossReport.from_dict(payload.pop("loss_report", {})),
            gate_results=tuple(raw_gates),
            aggregate_verdict=payload.pop("aggregate_verdict"),
            reason_code=payload.pop("reason_code"),
            profile_revision=payload.pop("profile_revision"),
            tokenizer_revision=payload.pop("tokenizer_revision"),
            normalizer_revision=payload.pop("normalizer_revision"),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_COMPRESSION_RECORD_SCHEMA_REVISION,
            ),
            record_id=payload.pop("record_id", None),
            checksum=payload.pop("checksum", None),
            created_at=parse_datetime(payload.pop("created_at", None)) or utc_now(),
        )
        reject_fields(payload, model="ContextCompressionRecordV2")
        return result


__all__ = [
    "CONTEXT_COMPRESSION_RECORD_SCHEMA_REVISION",
    "CONTEXT_SEMANTIC_SNAPSHOT_SCHEMA_REVISION",
    "ContextCompressionRecordV2",
    "ContextSemanticSnapshot",
    "ContextSemanticSnapshotKind",
]
