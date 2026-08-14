from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from datetime import datetime
from typing import Any

from framework.harness.context.models import ContextEnvelope
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.subagents.transcript import SubAgentTranscriptReceipt
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


FORBIDDEN_SUBAGENT_CONTEXT_KEYS = frozenset(
    {
        "parent_raw_messages",
        "sibling_raw_history",
        "sibling_private_notes",
        "hidden_prompt",
        "unapproved_memory",
        "unapproved_tool_results",
        "full_transcript",
    }
)

FORBIDDEN_SUBAGENT_RESULT_KEYS = frozenset(
    {
        "next_step",
        "quality_passed",
        "write_memory",
        "publish_artifact",
        "promote_skill",
        "halt_workflow",
    }
)


class SubAgentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    HALTED = "halted"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SubAgentSpec:
    subagent_id: str
    role: str
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_tools: tuple[str, ...]
    allowed_memory_namespaces: tuple[str, ...]
    context_policy: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.subagent_id).strip():
            raise HarnessValidationError("subagent_id is required")
        if not str(self.role).strip():
            raise HarnessValidationError("role is required")
        if not str(self.purpose).strip():
            raise HarnessValidationError("purpose is required")
        if not self.allowed_tools:
            raise HarnessValidationError("allowed_tools must be explicitly declared")
        if not self.allowed_memory_namespaces:
            raise HarnessValidationError("allowed_memory_namespaces must be explicitly declared")
        stable_json_dumps(self.input_schema)
        stable_json_dumps(self.output_schema)
        object.__setattr__(self, "subagent_id", str(self.subagent_id))
        object.__setattr__(self, "role", str(self.role))
        object.__setattr__(self, "purpose", str(self.purpose))
        object.__setattr__(self, "input_schema", dict(self.input_schema))
        object.__setattr__(self, "output_schema", dict(self.output_schema))
        object.__setattr__(self, "allowed_tools", tuple(str(tool) for tool in self.allowed_tools))
        object.__setattr__(
            self,
            "allowed_memory_namespaces",
            tuple(str(namespace) for namespace in self.allowed_memory_namespaces),
        )
        object.__setattr__(self, "context_policy", dict(self.context_policy))
        object.__setattr__(self, "budget", dict(self.budget))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subagent_id": self.subagent_id,
            "role": self.role,
            "purpose": self.purpose,
            "input_schema": to_jsonable(self.input_schema),
            "output_schema": to_jsonable(self.output_schema),
            "allowed_tools": list(self.allowed_tools),
            "allowed_memory_namespaces": list(self.allowed_memory_namespaces),
            "context_policy": to_jsonable(self.context_policy),
            "budget": to_jsonable(self.budget),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SubAgentContextEnvelope:
    child_run_id: str
    parent_run_id: str
    subagent_id: str
    role: str
    allowed_input_refs: tuple[str, ...]
    context_pack: ContextEnvelope | dict[str, Any]
    memory_context_refs: tuple[str, ...]
    tool_policy_ref: str
    budget_snapshot: HarnessBudgetSnapshot | dict[str, Any]
    redaction_report: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("child_run_id", "parent_run_id", "subagent_id", "role", "tool_policy_ref"):
            if not str(getattr(self, field_name)).strip():
                raise HarnessValidationError(f"{field_name} is required")
        context_payload = self.context_pack.to_dict() if isinstance(self.context_pack, ContextEnvelope) else dict(self.context_pack)
        forbidden = sorted(_find_forbidden_keys(context_payload, FORBIDDEN_SUBAGENT_CONTEXT_KEYS))
        if forbidden:
            raise HarnessValidationError("SubAgentContextEnvelope contains forbidden context fields", details={"forbidden": forbidden})
        object.__setattr__(self, "allowed_input_refs", tuple(str(ref) for ref in self.allowed_input_refs))
        object.__setattr__(self, "memory_context_refs", tuple(str(ref) for ref in self.memory_context_refs))
        object.__setattr__(self, "redaction_report", dict(self.redaction_report))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_run_id": self.child_run_id,
            "parent_run_id": self.parent_run_id,
            "subagent_id": self.subagent_id,
            "role": self.role,
            "allowed_input_refs": list(self.allowed_input_refs),
            "context_pack": to_jsonable(self.context_pack),
            "memory_context_refs": list(self.memory_context_refs),
            "tool_policy_ref": self.tool_policy_ref,
            "budget_snapshot": to_jsonable(self.budget_snapshot),
            "redaction_report": to_jsonable(self.redaction_report),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SubAgentInvocation:
    invocation_id: str
    parent_run_id: str
    child_run_id: str
    workflow_id: str
    step_id: str
    task_id: str
    task_instance_id: str
    attempt: int
    observed_at: datetime
    subagent_spec: SubAgentSpec
    input_refs: tuple[str, ...]
    context_envelope: SubAgentContextEnvelope
    budget_snapshot: HarnessBudgetSnapshot
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "invocation_id",
            "parent_run_id",
            "child_run_id",
            "workflow_id",
            "step_id",
            "task_id",
            "task_instance_id",
        ):
            if not str(getattr(self, field_name)).strip():
                raise HarnessValidationError(f"{field_name} is required")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt <= 0:
            raise HarnessValidationError("attempt must be a positive integer")
        observed_at = parse_datetime(self.observed_at)
        if observed_at is None:
            raise HarnessValidationError("observed_at must be a timezone-aware timestamp")
        if not isinstance(self.subagent_spec, SubAgentSpec):
            raise HarnessValidationError("subagent_spec must be SubAgentSpec")
        if not isinstance(self.context_envelope, SubAgentContextEnvelope):
            raise HarnessValidationError("context_envelope must be SubAgentContextEnvelope")
        if not isinstance(self.budget_snapshot, HarnessBudgetSnapshot):
            raise HarnessValidationError("budget_snapshot must be HarnessBudgetSnapshot")
        object.__setattr__(self, "input_refs", tuple(str(ref) for ref in self.input_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "observed_at", observed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "task_id": self.task_id,
            "task_instance_id": self.task_instance_id,
            "attempt": self.attempt,
            "observed_at": format_datetime(self.observed_at),
            "subagent_spec": self.subagent_spec.to_dict(),
            "input_refs": list(self.input_refs),
            "context_envelope": self.context_envelope.to_dict(),
            "budget_snapshot": self.budget_snapshot.to_dict(),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SubAgentHandoff:
    handoff_id: str
    from_subagent_id: str
    to_subagent_id: str
    parent_run_id: str
    payload: dict[str, Any]
    payload_schema: dict[str, Any]
    input_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    redaction_report: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in (
            "handoff_id",
            "from_subagent_id",
            "to_subagent_id",
            "parent_run_id",
        ):
            value = str(getattr(self, field_name))
            if not value.strip() or value != value.strip():
                raise HarnessValidationError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "payload",
            "payload_schema",
            "redaction_report",
            "metadata",
        ):
            if not isinstance(getattr(self, field_name), Mapping):
                raise HarnessValidationError(
                    f"{field_name} must be an object",
                    code="subagent_handoff_invalid_payload",
                )
        normalized_refs: dict[str, tuple[str, ...]] = {}
        for field_name in ("input_refs", "artifact_refs"):
            refs = getattr(self, field_name)
            if isinstance(refs, (str, bytes)) or not isinstance(
                refs,
                (list, tuple),
            ):
                raise HarnessValidationError(
                    f"{field_name} must be an array",
                    code="subagent_handoff_invalid_payload",
                )
            if any(
                not isinstance(ref, str)
                or not ref.strip()
                or ref != ref.strip()
                for ref in refs
            ):
                raise HarnessValidationError(
                    f"{field_name} must contain non-empty references",
                    code="subagent_handoff_invalid_payload",
                )
            normalized_refs[field_name] = tuple(refs)
        forbidden = sorted(
            _find_forbidden_keys(self.payload, FORBIDDEN_SUBAGENT_CONTEXT_KEYS)
        )
        if forbidden:
            raise HarnessValidationError(
                "SubAgentHandoff payload contains private fields",
                details={"forbidden": forbidden},
            )
        for field_name in (
            "payload",
            "payload_schema",
            "redaction_report",
            "metadata",
        ):
            stable_json_dumps(getattr(self, field_name))
        try:
            created_at = parse_datetime(self.created_at)
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "created_at must be a timezone-aware timestamp",
                code="subagent_handoff_invalid_payload",
            ) from exc
        if created_at is None:
            raise HarnessValidationError(
                "created_at must be a timezone-aware timestamp",
                code="subagent_handoff_invalid_payload",
            )
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "payload_schema", dict(self.payload_schema))
        object.__setattr__(self, "input_refs", normalized_refs["input_refs"])
        object.__setattr__(
            self,
            "artifact_refs",
            normalized_refs["artifact_refs"],
        )
        object.__setattr__(self, "redaction_report", dict(self.redaction_report))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "from_subagent_id": self.from_subagent_id,
            "to_subagent_id": self.to_subagent_id,
            "parent_run_id": self.parent_run_id,
            "payload": to_jsonable(self.payload),
            "payload_schema": to_jsonable(self.payload_schema),
            "input_refs": list(self.input_refs),
            "artifact_refs": list(self.artifact_refs),
            "redaction_report": to_jsonable(self.redaction_report),
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubAgentHandoff":
        if not isinstance(value, Mapping):
            raise HarnessValidationError("SubAgentHandoff must be an object")
        payload = dict(value)
        expected = {
            "handoff_id",
            "from_subagent_id",
            "to_subagent_id",
            "parent_run_id",
            "payload",
            "payload_schema",
            "input_refs",
            "artifact_refs",
            "redaction_report",
            "metadata",
            "created_at",
        }
        if set(payload) != expected:
            raise HarnessValidationError(
                "SubAgentHandoff fields are invalid",
                code="subagent_handoff_invalid_payload",
            )
        for field_name in (
            "payload",
            "payload_schema",
            "redaction_report",
            "metadata",
        ):
            if not isinstance(payload[field_name], Mapping):
                raise HarnessValidationError(
                    f"{field_name} must be an object",
                    code="subagent_handoff_invalid_payload",
                )
            payload[field_name] = dict(payload[field_name])
        for field_name in ("input_refs", "artifact_refs"):
            values = payload[field_name]
            if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
                raise HarnessValidationError(
                    f"{field_name} must be an array",
                    code="subagent_handoff_invalid_payload",
                )
            payload[field_name] = tuple(values)
        return cls(**payload)


@dataclass(frozen=True)
class SubAgentResult:
    invocation_id: str
    child_run_id: str
    subagent_id: str
    status: SubAgentStatus | str
    output: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    memory_write_candidates: tuple[dict[str, Any], ...] = ()
    tool_call_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    transcript_receipt: SubAgentTranscriptReceipt | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("invocation_id", "child_run_id", "subagent_id"):
            if not str(getattr(self, field_name)).strip():
                raise HarnessValidationError(f"{field_name} is required")
        forbidden = sorted(FORBIDDEN_SUBAGENT_RESULT_KEYS.intersection(self.output))
        if forbidden:
            raise HarnessValidationError("SubAgentResult output contains flow-control fields", details={"forbidden": forbidden})
        object.__setattr__(self, "status", SubAgentStatus(self.status))
        object.__setattr__(self, "output", dict(self.output))
        object.__setattr__(self, "artifact_refs", tuple(str(ref) for ref in self.artifact_refs))
        object.__setattr__(self, "memory_write_candidates", tuple(dict(candidate) for candidate in self.memory_write_candidates))
        object.__setattr__(self, "tool_call_refs", tuple(str(ref) for ref in self.tool_call_refs))
        object.__setattr__(self, "warnings", tuple(str(warning) for warning in self.warnings))
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))
        if self.transcript_receipt is not None and not isinstance(
            self.transcript_receipt,
            SubAgentTranscriptReceipt,
        ):
            raise HarnessValidationError("transcript_receipt must be SubAgentTranscriptReceipt")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def transcript_ref(self) -> str | None:
        """Read-only projection; the typed receipt remains authoritative."""

        return self.transcript_receipt.transcript_ref if self.transcript_receipt else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "child_run_id": self.child_run_id,
            "subagent_id": self.subagent_id,
            "status": self.status.value,
            "output": to_jsonable(self.output),
            "artifact_refs": list(self.artifact_refs),
            "memory_write_candidates": to_jsonable(list(self.memory_write_candidates)),
            "tool_call_refs": list(self.tool_call_refs),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "transcript_receipt": (
                self.transcript_receipt.to_dict()
                if self.transcript_receipt is not None
                else None
            ),
            "metadata": to_jsonable(self.metadata),
        }


__all__ = [
    "FORBIDDEN_SUBAGENT_CONTEXT_KEYS",
    "FORBIDDEN_SUBAGENT_RESULT_KEYS",
    "SubAgentContextEnvelope",
    "SubAgentHandoff",
    "SubAgentInvocation",
    "SubAgentResult",
    "SubAgentSpec",
    "SubAgentStatus",
]


def _find_forbidden_keys(payload: Any, forbidden_keys: frozenset[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in forbidden_keys:
                found.add(str(key))
            found.update(_find_forbidden_keys(value, forbidden_keys))
    elif isinstance(payload, list | tuple):
        for item in payload:
            found.update(_find_forbidden_keys(item, forbidden_keys))
    return found
