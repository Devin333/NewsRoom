from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from framework.harness.context.group_models import (
    ContextGroup,
    ContextGroupKind,
    ContextGroupMember,
    ContextGroupMemberKind,
    ContextProtectionReason,
    ContextReconstructionPolicy,
    ContextToolTransactionState,
)
from framework.harness.context.models import ContextSegment, ContextSegmentType
from framework.harness.context.verified_common import (
    frozen_mapping,
    mapping_tuple,
    optional_text,
    required_text,
    text_tuple,
)
from framework.harness.context.verified_records import (
    ContextSemanticSnapshot,
    ContextSemanticSnapshotKind,
)
from framework.harness.control_plane.errors import HarnessValidationError


@dataclass(frozen=True)
class ContextMaterializationRequest:
    run_id: str
    task_binding_ref: str
    policy_revision: str
    segments: tuple[ContextSegment, ...] = ()
    messages: tuple[Mapping[str, Any], ...] = ()
    evidence_items: tuple[Mapping[str, Any], ...] = ()
    authorized_tools: tuple[Mapping[str, Any], ...] = ()
    output_contract_ref: str | None = None
    requires_output_contract: bool = False
    retry_state_ref: str | None = None
    control_decision_refs: tuple[str, ...] = ()
    physical_profile_revision: str | None = None
    step_id: str | None = None
    diagnostic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for field_name in ("run_id", "task_binding_ref", "policy_revision"):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(self, "step_id", optional_text(self.step_id, field="step_id"))
        object.__setattr__(
            self,
            "output_contract_ref",
            optional_text(self.output_contract_ref, field="output_contract_ref"),
        )
        object.__setattr__(
            self,
            "retry_state_ref",
            optional_text(self.retry_state_ref, field="retry_state_ref"),
        )
        object.__setattr__(
            self,
            "physical_profile_revision",
            optional_text(
                self.physical_profile_revision,
                field="physical_profile_revision",
            ),
        )
        if not isinstance(self.requires_output_contract, bool):
            raise HarnessValidationError("requires_output_contract must be a boolean")
        segments = tuple(self.segments)
        if not all(isinstance(segment, ContextSegment) for segment in segments):
            raise HarnessValidationError("segments must contain ContextSegment values")
        object.__setattr__(self, "segments", segments)
        for field_name in ("messages", "evidence_items", "authorized_tools"):
            object.__setattr__(
                self,
                field_name,
                mapping_tuple(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "control_decision_refs",
            text_tuple(self.control_decision_refs, field="control_decision_refs"),
        )
        object.__setattr__(
            self,
            "diagnostic_metadata",
            frozen_mapping(self.diagnostic_metadata, field="diagnostic_metadata"),
        )


class ContextGroupStructureValidator:
    def validate(
        self,
        groups: tuple[ContextGroup, ...],
        *,
        requires_output_contract: bool,
    ) -> None:
        if not groups:
            raise HarnessValidationError("materialized context must contain groups")
        if requires_output_contract and not any(
            group.group_kind is ContextGroupKind.OUTPUT_CONTRACT for group in groups
        ):
            raise HarnessValidationError("required output contract group is missing")
        for group in groups:
            if group.group_kind is ContextGroupKind.TOOL_TRANSACTION:
                # ContextGroup performs member-level transaction validation.
                continue
            if any(
                member.member_kind
                in {ContextGroupMemberKind.TOOL_CALL, ContextGroupMemberKind.TOOL_RESULT}
                for member in group.members
            ):
                raise HarnessValidationError(
                    "tool call and result members must belong to a tool transaction group"
                )


class ContextGroupMaterializer:
    def __init__(self) -> None:
        self._structure = ContextGroupStructureValidator()

    def materialize(self, request: ContextMaterializationRequest) -> ContextSemanticSnapshot:
        if not isinstance(request, ContextMaterializationRequest):
            raise HarnessValidationError("request must be ContextMaterializationRequest")
        groups = (
            *self._groups_from_segments(request),
            *self._groups_from_messages(request.messages),
            *self._groups_from_evidence(request),
            *self._groups_from_tools(request.authorized_tools),
            *self._control_decision_groups(request.control_decision_refs),
        )
        if request.output_contract_ref is not None and not any(
            group.group_kind is ContextGroupKind.OUTPUT_CONTRACT
            and any(
                member.content_ref == request.output_contract_ref
                for member in group.members
            )
            for group in groups
        ):
            groups = (
                *groups,
                _single_ref_group(
                    kind=ContextGroupKind.OUTPUT_CONTRACT,
                    content_ref=request.output_contract_ref,
                    source_refs=(request.output_contract_ref,),
                    protection=(ContextProtectionReason.OUTPUT_CONTRACT,),
                    member_kind=ContextGroupMemberKind.SCHEMA,
                ),
            )
        if request.retry_state_ref is not None:
            groups = (
                *groups,
                _single_ref_group(
                    kind=ContextGroupKind.RUN_STATE,
                    content_ref=request.retry_state_ref,
                    source_refs=(request.retry_state_ref,),
                    protection=(ContextProtectionReason.RETRY_REPLAN_STATE,),
                    member_kind=ContextGroupMemberKind.CONTROL,
                ),
            )
        groups_tuple = tuple(groups)
        self._structure.validate(
            groups_tuple,
            requires_output_contract=request.requires_output_contract,
        )
        return ContextSemanticSnapshot(
            run_id=request.run_id,
            step_id=request.step_id,
            task_binding_ref=request.task_binding_ref,
            groups=groups_tuple,
            policy_revision=request.policy_revision,
            physical_profile_revision=request.physical_profile_revision,
            snapshot_kind=ContextSemanticSnapshotKind.SOURCE,
        )

    def _groups_from_segments(
        self,
        request: ContextMaterializationRequest,
    ) -> tuple[ContextGroup, ...]:
        groups: list[ContextGroup] = []
        for segment in request.segments:
            source_refs = tuple(dict.fromkeys((segment.content_ref, *segment.provenance_refs)))
            semantic_metadata = {
                "legacy_segment_id": segment.segment_id,
                "legacy_segment_type": segment.segment_type.value,
                "legacy_compression_level": segment.compression_level.value,
            }
            if segment.segment_type is ContextSegmentType.GLOBAL_POLICY:
                groups.append(
                    _single_ref_group(
                        kind=ContextGroupKind.SYSTEM_INSTRUCTION,
                        content_ref=segment.content_ref,
                        source_refs=source_refs,
                        protection=(ContextProtectionReason.GLOBAL_POLICY,),
                        semantic_metadata=semantic_metadata,
                    )
                )
            elif segment.segment_type is ContextSegmentType.WORKFLOW:
                groups.append(
                    _single_ref_group(
                        kind=ContextGroupKind.WORKFLOW_CONTRACT,
                        content_ref=segment.content_ref,
                        source_refs=source_refs,
                        protection=(ContextProtectionReason.WORKFLOW_CONTRACT,),
                        semantic_metadata=semantic_metadata,
                    )
                )
            elif segment.segment_type is ContextSegmentType.WORKER_CONTRACT:
                groups.append(
                    _single_ref_group(
                        kind=ContextGroupKind.WORKFLOW_CONTRACT,
                        content_ref=segment.content_ref,
                        source_refs=source_refs,
                        protection=(ContextProtectionReason.WORKFLOW_CONTRACT,),
                        semantic_metadata=semantic_metadata,
                    )
                )
                if segment.metadata.get("output_schema"):
                    groups.append(
                        _single_ref_group(
                            kind=ContextGroupKind.OUTPUT_CONTRACT,
                            content_ref=segment.content_ref,
                            source_refs=source_refs,
                            protection=(ContextProtectionReason.OUTPUT_CONTRACT,),
                            member_kind=ContextGroupMemberKind.SCHEMA,
                            semantic_metadata={
                                **semantic_metadata,
                                "output_contract_present": True,
                            },
                        )
                    )
            elif segment.segment_type is ContextSegmentType.RUN_STATE:
                reasons = (
                    (ContextProtectionReason.RETRY_REPLAN_STATE,)
                    if segment.metadata.get("retry_state")
                    or segment.metadata.get("replan_state")
                    else ()
                )
                groups.append(
                    _single_ref_group(
                        kind=ContextGroupKind.RUN_STATE,
                        content_ref=segment.content_ref,
                        source_refs=source_refs,
                        protection=reasons,
                        semantic_metadata=semantic_metadata,
                    )
                )
            elif segment.segment_type is ContextSegmentType.EVIDENCE_MEMORY:
                required_refs = _reference_list(
                    segment.metadata.get("required_citation_refs", ()),
                    field="segment.metadata.required_citation_refs",
                )
                migration_source_refs = _reference_list(
                    segment.metadata.get("source_refs", ()),
                    field="segment.metadata.source_refs",
                )
                groups.append(
                    _single_ref_group(
                        kind=ContextGroupKind.EVIDENCE,
                        content_ref=segment.content_ref,
                        source_refs=source_refs,
                        protection=(ContextProtectionReason.REQUIRED_EVIDENCE,)
                        if required_refs
                        else (),
                        member_kind=ContextGroupMemberKind.REFERENCE,
                        required_citation_refs=required_refs,
                        query_binding_ref=request.task_binding_ref,
                        semantic_metadata={
                            **semantic_metadata,
                            "migration_source_refs": list(migration_source_refs),
                        },
                    )
                )
            elif segment.segment_type is ContextSegmentType.CURRENT_TASK:
                groups.append(
                    _single_ref_group(
                        kind=ContextGroupKind.CURRENT_TASK,
                        content_ref=segment.content_ref,
                        source_refs=source_refs,
                        protection=(ContextProtectionReason.CURRENT_TASK,),
                        semantic_metadata=semantic_metadata,
                    )
                )
        return tuple(groups)

    def _groups_from_messages(
        self,
        messages: tuple[Mapping[str, Any], ...],
    ) -> tuple[ContextGroup, ...]:
        self._validate_role_order(messages)
        groups: list[ContextGroup] = []
        index = 0
        while index < len(messages):
            message = dict(messages[index])
            _reject_authority_overrides(message, field="message")
            _reject_raw_body_fields(message, field="message", fields=("content",))
            _reject_unknown_fields(
                message,
                field="message",
                allowed=_MESSAGE_FIELDS,
            )
            role = _message_role(message)
            if role == "tool":
                raise HarnessValidationError("orphan tool result has no assistant tool call")
            tool_calls = _message_tool_calls(message)
            if tool_calls:
                if role != "assistant":
                    raise HarnessValidationError(
                        "tool_calls must be an assistant message list"
                    )
                results: list[dict[str, Any]] = []
                cursor = index + 1
                while cursor < len(messages) and _message_role(messages[cursor]) == "tool":
                    results.append(dict(messages[cursor]))
                    cursor += 1
                groups.extend(self._tool_transaction_groups(message, tuple(tool_calls), results))
                index = cursor
                continue
            content_ref = _message_content_ref(message)
            protection = (
                (ContextProtectionReason.SAFETY_CONSTRAINT,)
                if role == "system"
                else ()
            )
            groups.append(
                ContextGroup(
                    group_kind=(
                        ContextGroupKind.SYSTEM_INSTRUCTION
                        if role == "system"
                        else ContextGroupKind.CONVERSATION_TURN
                    ),
                    members=(
                        ContextGroupMember(
                            member_kind=ContextGroupMemberKind.MESSAGE,
                            content_ref=content_ref,
                            ordinal=0,
                            role=role,
                            source_refs=_source_refs(message, fallback=content_ref),
                            semantic_metadata={"turn_id": _optional_turn_id(message)},
                            diagnostic_metadata=_mapping_value(
                                message.get("diagnostic_metadata", {}),
                                field="message.diagnostic_metadata",
                            ),
                        ),
                    ),
                    source_refs=_source_refs(message, fallback=content_ref),
                    protection_reasons=protection,
                    semantic_metadata={
                        "role": role,
                        "turn_id": _optional_turn_id(message),
                    },
                )
            )
            index += 1
        return tuple(groups)

    def _tool_transaction_groups(
        self,
        assistant_message: Mapping[str, Any],
        tool_calls: tuple[Any, ...],
        results: list[dict[str, Any]],
    ) -> tuple[ContextGroup, ...]:
        result_by_call: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            call_id = required_text(result.get("tool_call_id"), field="tool_call_id")
            result_by_call.setdefault(call_id, []).append(result)
            if len(result_by_call[call_id]) > 1:
                raise HarnessValidationError(
                    f"tool call {call_id} has ambiguous duplicate results"
                )
        groups: list[ContextGroup] = []
        known_call_ids: set[str] = set()
        for raw_call in tool_calls:
            if not isinstance(raw_call, Mapping):
                raise HarnessValidationError("tool call must be an object")
            call = dict(raw_call)
            _reject_authority_overrides(call, field="tool_call")
            _reject_raw_body_fields(
                call,
                field="tool_call",
                fields=("arguments", "input", "content"),
            )
            _reject_unknown_fields(
                call,
                field="tool_call",
                allowed=_TOOL_CALL_FIELDS,
            )
            call_id = required_text(call.get("id"), field="tool_call.id")
            tool_name = required_text(call.get("name"), field="tool_call.name")
            if call_id in known_call_ids:
                raise HarnessValidationError("tool call ids must be unique")
            known_call_ids.add(call_id)
            call_ref = required_text(
                call.get("content_ref") or assistant_message.get("content_ref"),
                field="tool_call.content_ref",
            )
            matching_results = result_by_call.get(call_id, [])
            members = [
                ContextGroupMember(
                    member_kind=ContextGroupMemberKind.TOOL_CALL,
                    content_ref=call_ref,
                    ordinal=0,
                    role="assistant",
                    tool_call_id=call_id,
                    source_refs=_source_refs(call, fallback=call_ref),
                    semantic_metadata={"tool_name": tool_name},
                )
            ]
            for ordinal, result in enumerate(matching_results, start=1):
                result_ref = _message_content_ref(result)
                members.append(
                    ContextGroupMember(
                        member_kind=ContextGroupMemberKind.TOOL_RESULT,
                        content_ref=result_ref,
                        ordinal=ordinal,
                        role="tool",
                        tool_call_id=call_id,
                        source_refs=_source_refs(result, fallback=result_ref),
                        semantic_metadata={"tool_name": tool_name},
                    )
                )
            state = (
                ContextToolTransactionState.COMPLETED
                if matching_results
                else ContextToolTransactionState.PENDING
            )
            groups.append(
                ContextGroup(
                    group_kind=ContextGroupKind.TOOL_TRANSACTION,
                    members=tuple(members),
                    source_refs=tuple(
                        dict.fromkeys(
                            ref for member in members for ref in member.source_refs
                        )
                    ),
                    protection_reasons=(ContextProtectionReason.PENDING_TOOL_TRANSACTION,)
                    if state is ContextToolTransactionState.PENDING
                    else (),
                    tool_transaction_state=state,
                    semantic_metadata={"tool_name": tool_name},
                )
            )
        orphan_ids = sorted(set(result_by_call).difference(known_call_ids))
        if orphan_ids:
            raise HarnessValidationError(
                "orphan tool result call ids: " + ", ".join(orphan_ids)
            )
        return tuple(groups)

    def _groups_from_evidence(
        self,
        request: ContextMaterializationRequest,
    ) -> tuple[ContextGroup, ...]:
        groups: list[ContextGroup] = []
        for item in request.evidence_items:
            evidence = dict(item)
            _reject_authority_overrides(evidence, field="evidence")
            _reject_unknown_fields(
                evidence,
                field="evidence",
                allowed=_EVIDENCE_FIELDS,
            )
            evidence_id = required_text(evidence.get("evidence_id"), field="evidence_id")
            source_refs = text_tuple(
                evidence.get("source_refs", ()),
                field="evidence.source_refs",
                required=True,
            )
            span_refs = text_tuple(
                evidence.get("span_refs", ()),
                field="evidence.span_refs",
                required=True,
            )
            lineage_refs = text_tuple(
                evidence.get("lineage_refs", ()),
                field="evidence.lineage_refs",
                required=True,
            )
            required_citations = text_tuple(
                evidence.get("required_citation_refs", ()),
                field="evidence.required_citation_refs",
            )
            required_span_refs = text_tuple(
                evidence.get("required_span_refs", ()),
                field="evidence.required_span_refs",
            )
            selected_span_refs = text_tuple(
                evidence.get("selected_span_refs", span_refs),
                field="evidence.selected_span_refs",
                required=True,
            )
            if not set(required_span_refs).issubset(span_refs):
                raise HarnessValidationError(
                    "evidence.required_span_refs must belong to span_refs"
                )
            if not set(selected_span_refs).issubset(span_refs):
                raise HarnessValidationError(
                    "evidence.selected_span_refs must belong to span_refs"
                )
            if not set(required_span_refs).issubset(selected_span_refs):
                raise HarnessValidationError(
                    "evidence.selected_span_refs must retain required_span_refs"
                )
            conflict_refs = text_tuple(
                evidence.get("conflict_refs", ()),
                field="evidence.conflict_refs",
            )
            required = _boolean_value(
                evidence.get("required", False),
                field="evidence.required",
            )
            members = tuple(
                ContextGroupMember(
                    member_kind=ContextGroupMemberKind.EVIDENCE_SPAN,
                    content_ref=span_ref,
                    ordinal=ordinal,
                    source_refs=source_refs,
                    semantic_metadata={
                        "evidence_id": evidence_id,
                        "lineage_refs": list(lineage_refs),
                    },
                )
                for ordinal, span_ref in enumerate(span_refs)
            )
            groups.append(
                ContextGroup(
                    group_kind=ContextGroupKind.EVIDENCE,
                    members=members,
                    source_refs=source_refs,
                    protection_reasons=(ContextProtectionReason.REQUIRED_EVIDENCE,)
                    if required_citations or required
                    else (),
                    query_binding_ref=request.task_binding_ref,
                    required_citation_refs=required_citations,
                    semantic_metadata={
                        "evidence_id": evidence_id,
                        "lineage_refs": list(lineage_refs),
                        "conflict_refs": list(conflict_refs),
                        "required_span_refs": list(required_span_refs),
                        "selected_span_refs": list(selected_span_refs),
                        "whole_group_required": required,
                    },
                    diagnostic_metadata=_mapping_value(
                        evidence.get("diagnostic_metadata", {}),
                        field="evidence.diagnostic_metadata",
                    ),
                )
            )
        return tuple(groups)

    def _groups_from_tools(
        self,
        tools: tuple[Mapping[str, Any], ...],
    ) -> tuple[ContextGroup, ...]:
        groups: list[ContextGroup] = []
        for raw_tool in tools:
            tool = dict(raw_tool)
            _reject_authority_overrides(tool, field="authorized_tool")
            _reject_unknown_fields(
                tool,
                field="authorized_tool",
                allowed=_AUTHORIZED_TOOL_FIELDS,
            )
            tool_id = required_text(tool.get("tool_id") or tool.get("name"), field="tool_id")
            schema_ref = required_text(tool.get("schema_ref"), field="tool.schema_ref")
            authorization_ref = required_text(
                tool.get("authorization_ref"),
                field="tool.authorization_ref",
            )
            required = _boolean_value(
                tool.get("required", False),
                field="tool.required",
            )
            reachable = _boolean_value(
                tool.get("reachable", True),
                field="tool.reachable",
            )
            groups.append(
                ContextGroup(
                    group_kind=ContextGroupKind.AUTHORIZED_TOOL_SCHEMA,
                    members=(
                        ContextGroupMember(
                            member_kind=ContextGroupMemberKind.SCHEMA,
                            content_ref=schema_ref,
                            ordinal=0,
                            source_refs=(schema_ref, authorization_ref),
                            semantic_metadata={"tool_id": tool_id},
                        ),
                    ),
                    source_refs=(schema_ref, authorization_ref),
                    protection_reasons=(ContextProtectionReason.CONTROL_DECISION,)
                    if required
                    else (),
                    reconstruction_policy=ContextReconstructionPolicy.DURABLE_REF,
                    reconstruction_ref=schema_ref,
                    semantic_metadata={
                        "tool_id": tool_id,
                        "authorization_ref": authorization_ref,
                        "reachable": reachable,
                    },
                )
            )
        return tuple(groups)

    def _control_decision_groups(
        self,
        refs: tuple[str, ...],
    ) -> tuple[ContextGroup, ...]:
        return tuple(
            _single_ref_group(
                kind=ContextGroupKind.RUN_STATE,
                content_ref=ref,
                source_refs=(ref,),
                protection=(ContextProtectionReason.CONTROL_DECISION,),
            )
            for ref in refs
        )

    def _validate_role_order(self, messages: tuple[Mapping[str, Any], ...]) -> None:
        state = "initial_user"
        pending_call_ids: set[str] = set()
        completed_call_ids: set[str] = set()
        seen_non_system = False
        for message in messages:
            role = _message_role(message)
            if role == "system":
                if seen_non_system:
                    raise HarnessValidationError(
                        "system message must precede conversation messages"
                    )
                continue
            seen_non_system = True
            tool_calls = _message_tool_calls(message)
            if role == "tool":
                if state != "tool_results":
                    raise HarnessValidationError(
                        "tool result must follow an assistant tool call"
                    )
                call_id = required_text(
                    message.get("tool_call_id"),
                    field="tool_call_id",
                )
                if call_id not in pending_call_ids:
                    raise HarnessValidationError(
                        "tool result must match a pending assistant tool call"
                    )
                if call_id in completed_call_ids:
                    raise HarnessValidationError(
                        f"tool call {call_id} has ambiguous duplicate results"
                    )
                completed_call_ids.add(call_id)
                continue
            if state == "tool_results":
                if completed_call_ids != pending_call_ids:
                    raise HarnessValidationError(
                        "conversation cannot continue after partial tool results"
                    )
                if role != "assistant":
                    raise HarnessValidationError(
                        "completed tool results must be followed by an assistant message"
                    )
                state = "assistant_after_tool"
            if state == "initial_user" and role != "user":
                raise HarnessValidationError(
                    "conversation history must start with a user message"
                )
            if state == "user" and role != "user":
                raise HarnessValidationError(
                    "user and assistant conversation roles must alternate"
                )
            if state == "assistant" and role != "assistant":
                raise HarnessValidationError(
                    "user and assistant conversation roles must alternate"
                )
            if role == "user":
                if tool_calls:
                    raise HarnessValidationError(
                        "tool_calls must belong to an assistant message"
                    )
                state = "assistant"
                continue
            if role != "assistant":
                raise HarnessValidationError("unsupported conversation transition")
            if tool_calls:
                if not isinstance(tool_calls, (list, tuple)) or not tool_calls:
                    raise HarnessValidationError(
                        "tool_calls must be a non-empty assistant message list"
                    )
                pending_call_ids = _tool_call_ids(tool_calls)
                completed_call_ids = set()
                state = "tool_results"
            else:
                state = "user"


def _single_ref_group(
    *,
    kind: ContextGroupKind,
    content_ref: str,
    source_refs: tuple[str, ...],
    protection: tuple[ContextProtectionReason, ...] = (),
    member_kind: ContextGroupMemberKind = ContextGroupMemberKind.CONTROL,
    reconstruction_policy: ContextReconstructionPolicy = ContextReconstructionPolicy.NONE,
    reconstruction_ref: str | None = None,
    query_binding_ref: str | None = None,
    required_citation_refs: tuple[str, ...] = (),
    semantic_metadata: Mapping[str, Any] | None = None,
) -> ContextGroup:
    return ContextGroup(
        group_kind=kind,
        members=(
            ContextGroupMember(
                member_kind=member_kind,
                content_ref=content_ref,
                ordinal=0,
                source_refs=source_refs,
                semantic_metadata=semantic_metadata or {},
            ),
        ),
        source_refs=source_refs,
        protection_reasons=protection,
        reconstruction_policy=reconstruction_policy,
        reconstruction_ref=reconstruction_ref,
        query_binding_ref=query_binding_ref,
        required_citation_refs=required_citation_refs,
        semantic_metadata=semantic_metadata or {},
    )


def _message_role(message: Mapping[str, Any]) -> str:
    role = required_text(message.get("role"), field="message.role").casefold()
    if role not in {"system", "user", "assistant", "tool"}:
        raise HarnessValidationError(f"unsupported message role: {role}")
    return role


def _message_content_ref(message: Mapping[str, Any]) -> str:
    _reject_raw_body_fields(message, field="message", fields=("content",))
    return required_text(message.get("content_ref"), field="message.content_ref")


def _message_tool_calls(message: Mapping[str, Any]) -> tuple[Any, ...]:
    value = message.get("tool_calls", ())
    if not isinstance(value, (list, tuple)):
        raise HarnessValidationError("message.tool_calls must be a list")
    return tuple(value)


def _source_refs(message: Mapping[str, Any], *, fallback: str) -> tuple[str, ...]:
    raw = message.get("source_refs")
    if raw is None:
        return (fallback,)
    return text_tuple(raw, field="message.source_refs", required=True)


def _reference_list(value: Any, *, field: str) -> tuple[str, ...]:
    return text_tuple(value, field=field)


def _mapping_value(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{field} must be an object")
    return dict(value)


def _boolean_value(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise HarnessValidationError(f"{field} must be a boolean")
    return value


def _optional_turn_id(message: Mapping[str, Any]) -> str | None:
    return optional_text(message.get("turn_id"), field="message.turn_id")


def _tool_call_ids(tool_calls: Any) -> set[str]:
    call_ids: set[str] = set()
    for raw_call in tool_calls:
        if not isinstance(raw_call, Mapping):
            raise HarnessValidationError("tool call must be an object")
        call_id = required_text(raw_call.get("id"), field="tool_call.id")
        if call_id in call_ids:
            raise HarnessValidationError("tool call ids must be unique")
        call_ids.add(call_id)
    return call_ids


_MESSAGE_FIELDS = frozenset(
    {
        "content_ref",
        "diagnostic_metadata",
        "role",
        "source_refs",
        "tool_call_id",
        "tool_calls",
        "turn_id",
    }
)
_TOOL_CALL_FIELDS = frozenset({"content_ref", "id", "name", "source_refs"})
_EVIDENCE_FIELDS = frozenset(
    {
        "conflict_refs",
        "diagnostic_metadata",
        "evidence_id",
        "lineage_refs",
        "required",
        "required_citation_refs",
        "required_span_refs",
        "selected_span_refs",
        "source_refs",
        "span_refs",
    }
)
_AUTHORIZED_TOOL_FIELDS = frozenset(
    {
        "authorization_ref",
        "name",
        "reachable",
        "required",
        "schema_ref",
        "tool_id",
    }
)


_REQUEST_AUTHORITY_OVERRIDE_FIELDS = frozenset(
    {
        "context_profile",
        "gate_passed",
        "max_context_tokens",
        "max_input_tokens",
        "physical_profile_revision",
        "profile_revision",
        "protected",
        "protection_reasons",
        "trusted",
        "verified",
    }
)


def _reject_authority_overrides(value: Mapping[str, Any], *, field: str) -> None:
    overrides = sorted(_REQUEST_AUTHORITY_OVERRIDE_FIELDS.intersection(value))
    if overrides:
        raise HarnessValidationError(
            f"{field} contains authority overrides: " + ", ".join(overrides)
        )


def _reject_unknown_fields(
    value: Mapping[str, Any],
    *,
    field: str,
    allowed: frozenset[str],
) -> None:
    unknown = sorted(str(name) for name in set(value).difference(allowed))
    if unknown:
        raise HarnessValidationError(
            f"{field} contains unsupported fields: " + ", ".join(unknown)
        )


def _reject_raw_body_fields(
    value: Mapping[str, Any],
    *,
    field: str,
    fields: tuple[str, ...],
) -> None:
    present = sorted(name for name in fields if name in value)
    if present:
        raise HarnessValidationError(
            f"{field} requires refs; raw fields are unsupported: "
            + ", ".join(present)
        )


__all__ = [
    "ContextGroupMaterializer",
    "ContextGroupStructureValidator",
    "ContextMaterializationRequest",
]
