from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from framework.harness.context.verified_common import (
    frozen_mapping,
    identity,
    non_negative_int,
    optional_text,
    reject_fields,
    required_text,
    strict_payload,
    text_tuple,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


CONTEXT_GROUP_SCHEMA_REVISION = "newsroom.context-group/v1"
CONTEXT_GROUP_MEMBER_SCHEMA_REVISION = "newsroom.context-group-member/v1"


class ContextGroupKind(StrEnum):
    SYSTEM_INSTRUCTION = "system_instruction"
    GRAPH_CONTRACT = "graph_contract"
    CURRENT_TASK = "current_task"
    OUTPUT_CONTRACT = "output_contract"
    RUN_STATE = "run_state"
    TOOL_TRANSACTION = "tool_transaction"
    EVIDENCE = "evidence"
    CONVERSATION_TURN = "conversation_turn"
    MEMORY_REFERENCE = "memory_reference"
    RECONSTRUCTABLE = "reconstructable"
    AUTHORIZED_TOOL_SCHEMA = "authorized_tool_schema"


class ContextGroupMemberKind(StrEnum):
    MESSAGE = "message"
    CONTROL = "control"
    SCHEMA = "schema"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    EVIDENCE_SPAN = "evidence_span"
    REFERENCE = "reference"


class ContextProtectionReason(StrEnum):
    GLOBAL_POLICY = "global_policy"
    SAFETY_CONSTRAINT = "safety_constraint"
    GRAPH_CONTRACT = "graph_contract"
    CURRENT_TASK = "current_task"
    OUTPUT_CONTRACT = "output_contract"
    PENDING_TOOL_TRANSACTION = "pending_tool_transaction"
    RETRY_REPLAN_STATE = "retry_replan_state"
    REQUIRED_EVIDENCE = "required_evidence"
    CONTROL_DECISION = "control_decision"


class ContextReconstructionPolicy(StrEnum):
    NONE = "none"
    DURABLE_REF = "durable_ref"
    SOURCE_RETRIEVAL = "source_retrieval"


class ContextToolTransactionState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    COMPLETED = "completed"
    PENDING = "pending"
    UNRESOLVED = "unresolved"
    FAILED = "failed"


@dataclass(frozen=True)
class ContextGroupMember:
    member_kind: ContextGroupMemberKind | str
    content_ref: str
    ordinal: int
    role: str | None = None
    tool_call_id: str | None = None
    source_refs: tuple[str, ...] = ()
    semantic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    diagnostic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    schema_revision: str = CONTEXT_GROUP_MEMBER_SCHEMA_REVISION
    member_id: str | None = None
    identity_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_kind", ContextGroupMemberKind(self.member_kind))
        object.__setattr__(self, "content_ref", required_text(self.content_ref, field="content_ref"))
        object.__setattr__(self, "ordinal", non_negative_int(self.ordinal, field="ordinal"))
        object.__setattr__(self, "role", optional_text(self.role, field="role"))
        object.__setattr__(
            self,
            "tool_call_id",
            optional_text(self.tool_call_id, field="tool_call_id"),
        )
        object.__setattr__(
            self,
            "source_refs",
            text_tuple(self.source_refs, field="source_refs"),
        )
        object.__setattr__(
            self,
            "semantic_metadata",
            frozen_mapping(self.semantic_metadata, field="semantic_metadata"),
        )
        object.__setattr__(
            self,
            "diagnostic_metadata",
            frozen_mapping(self.diagnostic_metadata, field="diagnostic_metadata"),
        )
        object.__setattr__(
            self,
            "schema_revision",
            required_text(self.schema_revision, field="schema_revision"),
        )
        expected_id, checksum = identity("context-member", self.identity_projection())
        if self.member_id is not None and self.member_id != expected_id:
            raise HarnessValidationError("member_id does not match member semantic identity")
        if self.identity_checksum is not None and self.identity_checksum != checksum:
            raise HarnessValidationError(
                "member identity_checksum does not match member semantic identity"
            )
        object.__setattr__(self, "member_id", expected_id)
        object.__setattr__(self, "identity_checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "member_kind": self.member_kind.value,
            "content_ref": self.content_ref,
            "ordinal": self.ordinal,
            "role": self.role,
            "tool_call_id": self.tool_call_id,
            "source_refs": list(self.source_refs),
            "semantic_metadata": to_jsonable(dict(self.semantic_metadata)),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "member_id": self.member_id,
            "identity_checksum": self.identity_checksum,
            "diagnostic_metadata": to_jsonable(dict(self.diagnostic_metadata)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextGroupMember:
        payload = strict_payload(value, model="ContextGroupMember")
        result = cls(
            member_kind=payload.pop("member_kind"),
            content_ref=payload.pop("content_ref"),
            ordinal=payload.pop("ordinal"),
            role=payload.pop("role", None),
            tool_call_id=payload.pop("tool_call_id", None),
            source_refs=payload.pop("source_refs", ()),
            semantic_metadata=payload.pop("semantic_metadata", {}),
            diagnostic_metadata=payload.pop("diagnostic_metadata", {}),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_GROUP_MEMBER_SCHEMA_REVISION,
            ),
            member_id=payload.pop("member_id", None),
            identity_checksum=payload.pop("identity_checksum", None),
        )
        reject_fields(payload, model="ContextGroupMember")
        return result


@dataclass(frozen=True)
class ContextGroup:
    group_kind: ContextGroupKind | str
    members: tuple[ContextGroupMember, ...]
    source_refs: tuple[str, ...]
    protection_reasons: tuple[ContextProtectionReason | str, ...] = ()
    reconstruction_policy: ContextReconstructionPolicy | str = ContextReconstructionPolicy.NONE
    reconstruction_ref: str | None = None
    tool_transaction_state: ContextToolTransactionState | str = (
        ContextToolTransactionState.NOT_APPLICABLE
    )
    query_binding_ref: str | None = None
    required_citation_refs: tuple[str, ...] = ()
    semantic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    diagnostic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    schema_revision: str = CONTEXT_GROUP_SCHEMA_REVISION
    group_id: str | None = None
    identity_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_kind", ContextGroupKind(self.group_kind))
        if not isinstance(self.members, (list, tuple)) or not self.members:
            raise HarnessValidationError("members must be a non-empty list")
        members = tuple(self.members)
        if not all(isinstance(member, ContextGroupMember) for member in members):
            raise HarnessValidationError("members must contain ContextGroupMember values")
        if tuple(member.ordinal for member in members) != tuple(range(len(members))):
            raise HarnessValidationError("member ordinals must be contiguous and ordered")
        object.__setattr__(self, "members", members)
        object.__setattr__(
            self,
            "source_refs",
            text_tuple(self.source_refs, field="source_refs", required=True),
        )
        try:
            reasons = tuple(ContextProtectionReason(reason) for reason in self.protection_reasons)
        except ValueError as exc:
            raise HarnessValidationError("unsupported context protection reason") from exc
        if len(set(reasons)) != len(reasons):
            raise HarnessValidationError("protection_reasons must not contain duplicates")
        object.__setattr__(self, "protection_reasons", reasons)
        object.__setattr__(
            self,
            "reconstruction_policy",
            ContextReconstructionPolicy(self.reconstruction_policy),
        )
        object.__setattr__(
            self,
            "reconstruction_ref",
            optional_text(self.reconstruction_ref, field="reconstruction_ref"),
        )
        if (
            self.reconstruction_policy is ContextReconstructionPolicy.NONE
            and self.reconstruction_ref is not None
        ):
            raise HarnessValidationError(
                "reconstruction_ref requires a non-none reconstruction_policy"
            )
        if (
            self.reconstruction_policy is not ContextReconstructionPolicy.NONE
            and self.reconstruction_ref is None
        ):
            raise HarnessValidationError(
                "reconstruction_policy requires reconstruction_ref"
            )
        object.__setattr__(
            self,
            "tool_transaction_state",
            ContextToolTransactionState(self.tool_transaction_state),
        )
        if (
            self.group_kind is not ContextGroupKind.TOOL_TRANSACTION
            and self.tool_transaction_state is not ContextToolTransactionState.NOT_APPLICABLE
        ):
            raise HarnessValidationError(
                "tool_transaction_state applies only to tool transaction groups"
            )
        if self.group_kind is ContextGroupKind.TOOL_TRANSACTION:
            self._validate_tool_transaction()
        object.__setattr__(
            self,
            "query_binding_ref",
            optional_text(self.query_binding_ref, field="query_binding_ref"),
        )
        object.__setattr__(
            self,
            "required_citation_refs",
            text_tuple(self.required_citation_refs, field="required_citation_refs"),
        )
        object.__setattr__(
            self,
            "semantic_metadata",
            frozen_mapping(self.semantic_metadata, field="semantic_metadata"),
        )
        object.__setattr__(
            self,
            "diagnostic_metadata",
            frozen_mapping(self.diagnostic_metadata, field="diagnostic_metadata"),
        )
        object.__setattr__(
            self,
            "schema_revision",
            required_text(self.schema_revision, field="schema_revision"),
        )
        expected_id, checksum = identity("context-group", self.identity_projection())
        if self.group_id is not None and self.group_id != expected_id:
            raise HarnessValidationError("group_id does not match group semantic identity")
        if self.identity_checksum is not None and self.identity_checksum != checksum:
            raise HarnessValidationError(
                "group identity_checksum does not match group semantic identity"
            )
        object.__setattr__(self, "group_id", expected_id)
        object.__setattr__(self, "identity_checksum", checksum)

    @property
    def protected(self) -> bool:
        return bool(self.protection_reasons)

    def _validate_tool_transaction(self) -> None:
        call_members = [
            member for member in self.members if member.member_kind is ContextGroupMemberKind.TOOL_CALL
        ]
        result_members = [
            member for member in self.members if member.member_kind is ContextGroupMemberKind.TOOL_RESULT
        ]
        if len(call_members) != 1:
            raise HarnessValidationError(
                "tool transaction must contain exactly one tool-call member"
            )
        call_id = call_members[0].tool_call_id
        if call_id is None or any(member.tool_call_id != call_id for member in result_members):
            raise HarnessValidationError("tool result members must match the transaction call id")
        if (
            self.tool_transaction_state is ContextToolTransactionState.COMPLETED
            and not result_members
        ):
            raise HarnessValidationError(
                "completed tool transaction requires at least one tool result"
            )
        if self.tool_transaction_state in {
            ContextToolTransactionState.PENDING,
            ContextToolTransactionState.UNRESOLVED,
        } and ContextProtectionReason.PENDING_TOOL_TRANSACTION not in self.protection_reasons:
            raise HarnessValidationError(
                "pending or unresolved tool transaction must be protected"
            )

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "group_kind": self.group_kind.value,
            "members": [member.identity_projection() for member in self.members],
            "source_refs": list(self.source_refs),
            "protection_reasons": [reason.value for reason in self.protection_reasons],
            "reconstruction_policy": self.reconstruction_policy.value,
            "reconstruction_ref": self.reconstruction_ref,
            "tool_transaction_state": self.tool_transaction_state.value,
            "query_binding_ref": self.query_binding_ref,
            "required_citation_refs": list(self.required_citation_refs),
            "semantic_metadata": to_jsonable(dict(self.semantic_metadata)),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "members": [member.to_dict() for member in self.members],
            "group_id": self.group_id,
            "identity_checksum": self.identity_checksum,
            "diagnostic_metadata": to_jsonable(dict(self.diagnostic_metadata)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextGroup:
        payload = strict_payload(value, model="ContextGroup")
        raw_members = payload.pop("members")
        if not isinstance(raw_members, (list, tuple)):
            raise HarnessValidationError("ContextGroup.members must be a list")
        result = cls(
            group_kind=payload.pop("group_kind"),
            members=tuple(ContextGroupMember.from_dict(member) for member in raw_members),
            source_refs=payload.pop("source_refs"),
            protection_reasons=tuple(payload.pop("protection_reasons", ())),
            reconstruction_policy=payload.pop(
                "reconstruction_policy",
                ContextReconstructionPolicy.NONE,
            ),
            reconstruction_ref=payload.pop("reconstruction_ref", None),
            tool_transaction_state=payload.pop(
                "tool_transaction_state",
                ContextToolTransactionState.NOT_APPLICABLE,
            ),
            query_binding_ref=payload.pop("query_binding_ref", None),
            required_citation_refs=payload.pop("required_citation_refs", ()),
            semantic_metadata=payload.pop("semantic_metadata", {}),
            diagnostic_metadata=payload.pop("diagnostic_metadata", {}),
            schema_revision=payload.pop("schema_revision", CONTEXT_GROUP_SCHEMA_REVISION),
            group_id=payload.pop("group_id", None),
            identity_checksum=payload.pop("identity_checksum", None),
        )
        reject_fields(payload, model="ContextGroup")
        return result


__all__ = [
    "CONTEXT_GROUP_MEMBER_SCHEMA_REVISION",
    "CONTEXT_GROUP_SCHEMA_REVISION",
    "ContextGroup",
    "ContextGroupKind",
    "ContextGroupMember",
    "ContextGroupMemberKind",
    "ContextProtectionReason",
    "ContextReconstructionPolicy",
    "ContextToolTransactionState",
]
