from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Protocol, Self, runtime_checkable

from framework.events.canonical import checksum_for, normalize_canonical_json
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.redaction import redact_sensitive_values
from framework.shared.time import format_datetime, parse_datetime, utc_now


SUBAGENT_CONTEXT_SCHEMA = "newsroom.subagent-context-evidence/v1"
SUBAGENT_OUTPUT_SCHEMA = "newsroom.subagent-output-document/v1"
SUBAGENT_TRANSCRIPT_SCHEMA = "newsroom.subagent-transcript/v1"
SUBAGENT_RECEIPT_SCHEMA = "newsroom.subagent-transcript-receipt/v1"
SUBAGENT_BUNDLE_SCHEMA = "newsroom.subagent-attempt-bundle/v1"
DEFAULT_MAX_TRANSCRIPT_BYTES = 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_BUNDLE_BYTES = 12 * 1024 * 1024
MAX_PARENT_QUERY = 256
_REASON_CODE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")

_FORBIDDEN_KEYS = frozenset(
    {
        "parent_raw_messages",
        "sibling_raw_history",
        "sibling_private_notes",
        "hidden_prompt",
        "raw_payload",
        "full_text",
        "authorization",
        "apikey",
        "cookie",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "client_secret",
        "credential",
        "private_key",
        "token",
        "dsn",
    }
)


class SubAgentTranscriptStoreError(HarnessValidationError):
    """Stable typed failure from a transcript persistence boundary."""


class SubAgentTranscriptConflictError(SubAgentTranscriptStoreError):
    pass


class SubAgentTranscriptCorruptError(SubAgentTranscriptStoreError):
    pass


def _required(value: Any, field_name: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise HarnessValidationError(
            f"{field_name} must be a non-blank trimmed string",
            code="subagent_transcript_invalid_field",
            details={"field": field_name},
        )
    if len(value) > max_length:
        raise HarnessValidationError(
            f"{field_name} exceeds its maximum length",
            code="subagent_transcript_field_too_long",
            details={"field": field_name, "max_length": max_length},
        )
    return value


def _optional(value: Any, field_name: str, *, max_length: int = 512) -> str | None:
    if value is None:
        return None
    return _required(value, field_name, max_length=max_length)


def _positive(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="subagent_transcript_invalid_field",
            details={"field": field_name},
        )
    return value


def _nonnegative(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessValidationError(
            f"{field_name} must be a non-negative integer",
            code="subagent_transcript_invalid_field",
            details={"field": field_name},
        )
    return value


def _checksum(value: Any, field_name: str) -> str:
    text = _required(value, field_name, max_length=71)
    if not text.startswith("sha256:") or len(text) != 71:
        raise HarnessValidationError(
            f"{field_name} must be a sha256 checksum",
            code="subagent_transcript_invalid_checksum",
            details={"field": field_name},
        )
    return text


def _refs(value: Sequence[str], field_name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="subagent_transcript_invalid_refs",
        )
    normalized = tuple(_required(str(item), field_name, max_length=2048) for item in value)
    if not allow_empty and not normalized:
        raise HarnessValidationError(
            f"{field_name} must not be empty",
            code="subagent_transcript_invalid_refs",
        )
    if len(set(normalized)) != len(normalized):
        raise HarnessValidationError(
            f"{field_name} must contain unique refs",
            code="subagent_transcript_duplicate_ref",
        )
    return normalized


def _mapping(value: Any, field_name: str, *, max_bytes: int | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="subagent_transcript_invalid_mapping",
        )
    payload = _sanitize_value(dict(value), path=f"$.{field_name}")
    try:
        frozen = normalize_canonical_json(payload, path=f"$.{field_name}")
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(
            f"{field_name} must be canonical JSON",
            code="subagent_transcript_noncanonical_payload",
        ) from exc
    if not isinstance(frozen, Mapping):
        raise HarnessValidationError(
            f"{field_name} must remain an object",
            code="subagent_transcript_invalid_mapping",
        )
    if max_bytes is not None and len(stable_json_dumps(frozen).encode("utf-8")) > max_bytes:
        raise HarnessValidationError(
            f"{field_name} exceeds its size limit",
            code="subagent_transcript_size_exceeded",
            details={"field": field_name, "max_bytes": max_bytes},
        )
    return frozen


def sanitize_subagent_payload(
    value: Mapping[str, Any],
    *,
    field_name: str = "output",
    max_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Return the bounded canonical JSON payload that is safe to persist and expose."""

    sanitized = to_jsonable(_mapping(value, field_name, max_bytes=max_bytes))
    if not isinstance(sanitized, dict):
        raise HarnessValidationError(
            f"{field_name} must remain an object",
            code="subagent_transcript_invalid_mapping",
        )
    return sanitized


def _timestamp(value: Any, field_name: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise HarnessValidationError(
            f"{field_name} must be a timezone-aware timestamp",
            code="subagent_transcript_invalid_timestamp",
        )
    return parsed


def _sanitize_value(value: Any, *, path: str) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            string_key = str(key)
            normalized = string_key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS or normalized.endswith("_raw"):
                raise HarnessValidationError(
                    "subagent evidence contains forbidden private fields",
                    code="subagent_transcript_private_content_rejected",
                    details={"field": f"{path}.{key}"},
                )
            if string_key in sanitized:
                raise HarnessValidationError(
                    "subagent evidence contains colliding canonical keys",
                    code="subagent_transcript_noncanonical_payload",
                    details={"field": f"{path}.{string_key}"},
                )
            sanitized[string_key] = _sanitize_value(item, path=f"{path}.{key}")
        return sanitized
    elif isinstance(value, (list, tuple)):
        return [_sanitize_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        sanitized = redact_sensitive_values(value)
        if sanitized != value:
            raise HarnessValidationError(
                "subagent evidence contains a secret-like value",
                code="subagent_transcript_secret_content_rejected",
                details={"field": path},
            )
        return value
    return value


def _verify_checksum(payload: Mapping[str, Any], supplied: str, field_name: str) -> None:
    expected = checksum_for(payload)
    if expected != supplied:
        raise HarnessValidationError(
            f"{field_name} does not match canonical content",
            code="subagent_transcript_checksum_mismatch",
            details={"field": field_name},
        )


@dataclass(frozen=True, slots=True)
class SubAgentAttemptIdentity:
    invocation_id: str
    parent_run_id: str
    child_run_id: str
    workflow_id: str
    stage_id: str
    task_id: str
    task_instance_id: str
    attempt: int
    subagent_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "invocation_id",
            "parent_run_id",
            "child_run_id",
            "workflow_id",
            "stage_id",
            "task_id",
            "task_instance_id",
            "subagent_id",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        object.__setattr__(self, "attempt", _positive(self.attempt, "attempt"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "workflow_id": self.workflow_id,
            "stage_id": self.stage_id,
            "task_id": self.task_id,
            "task_instance_id": self.task_instance_id,
            "attempt": self.attempt,
            "subagent_id": self.subagent_id,
        }

    @property
    def identity_checksum(self) -> str:
        return checksum_for(self.to_dict())

    @property
    def transcript_id(self) -> str:
        return f"sat_{self.identity_checksum.removeprefix('sha256:')}"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected = {
            "invocation_id", "parent_run_id", "child_run_id", "workflow_id",
            "stage_id", "task_id", "task_instance_id", "attempt", "subagent_id",
        }
        if set(value) != expected:
            raise HarnessValidationError(
                "SubAgentAttemptIdentity fields are invalid",
                code="subagent_transcript_invalid_payload",
            )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class SubAgentContextEvidence:
    identity: SubAgentAttemptIdentity
    context_envelope_ref: str
    input_refs: tuple[str, ...]
    memory_context_refs: tuple[str, ...]
    redaction_report: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SUBAGENT_CONTEXT_SCHEMA
    context_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SubAgentAttemptIdentity):
            raise TypeError("identity must be SubAgentAttemptIdentity")
        if self.schema_version != SUBAGENT_CONTEXT_SCHEMA:
            raise HarnessValidationError("unsupported subagent context schema", code="subagent_transcript_schema_unsupported")
        object.__setattr__(self, "context_envelope_ref", _required(self.context_envelope_ref, "context_envelope_ref", max_length=2048))
        object.__setattr__(self, "input_refs", _refs(self.input_refs, "input_refs", allow_empty=False))
        object.__setattr__(self, "memory_context_refs", _refs(self.memory_context_refs, "memory_context_refs"))
        object.__setattr__(self, "redaction_report", _mapping(self.redaction_report, "redaction_report"))
        object.__setattr__(self, "context_checksum", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "context_envelope_ref": self.context_envelope_ref,
            "input_refs": list(self.input_refs),
            "memory_context_refs": list(self.memory_context_refs),
            "redaction_report": to_jsonable(self.redaction_report),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "context_checksum": self.context_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = dict(value)
        supplied = _checksum(payload.pop("context_checksum", None), "context_checksum")
        raw_identity = payload.pop("identity", None)
        if not isinstance(raw_identity, Mapping):
            raise HarnessValidationError("context identity is required", code="subagent_transcript_invalid_payload")
        result = cls(identity=SubAgentAttemptIdentity.from_dict(raw_identity), **payload)
        _verify_checksum(result.checksum_projection(), supplied, "context_checksum")
        return result


@dataclass(frozen=True, slots=True)
class SubAgentOutputDocument:
    identity: SubAgentAttemptIdentity
    status: str
    output: Mapping[str, Any]
    artifact_refs: tuple[str, ...] = ()
    error_code: str | None = None
    schema_version: str = SUBAGENT_OUTPUT_SCHEMA
    output_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SubAgentAttemptIdentity):
            raise TypeError("identity must be SubAgentAttemptIdentity")
        if self.schema_version != SUBAGENT_OUTPUT_SCHEMA:
            raise HarnessValidationError("unsupported subagent output schema", code="subagent_transcript_schema_unsupported")
        object.__setattr__(self, "status", _required(self.status, "status", max_length=32))
        if self.status not in {"succeeded", "failed", "halted", "blocked"}:
            raise HarnessValidationError("unsupported subagent output status", code="subagent_transcript_invalid_status")
        object.__setattr__(self, "output", _mapping(self.output, "output", max_bytes=DEFAULT_MAX_OUTPUT_BYTES))
        object.__setattr__(self, "artifact_refs", _refs(self.artifact_refs, "artifact_refs"))
        object.__setattr__(self, "error_code", _optional(self.error_code, "error_code", max_length=128))
        object.__setattr__(self, "output_checksum", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "status": self.status,
            "output": to_jsonable(self.output),
            "artifact_refs": list(self.artifact_refs),
            "error_code": self.error_code,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "output_checksum": self.output_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = dict(value)
        supplied = _checksum(payload.pop("output_checksum", None), "output_checksum")
        raw_identity = payload.pop("identity", None)
        if not isinstance(raw_identity, Mapping):
            raise HarnessValidationError("output identity is required", code="subagent_transcript_invalid_payload")
        result = cls(identity=SubAgentAttemptIdentity.from_dict(raw_identity), **payload)
        _verify_checksum(result.checksum_projection(), supplied, "output_checksum")
        return result

    @property
    def ref(self) -> str:
        return f"subagent-output://v1/{self.identity.parent_run_id}/{self.identity.transcript_id}"


@dataclass(frozen=True, slots=True)
class SubAgentTranscript:
    identity: SubAgentAttemptIdentity
    context_envelope_ref: str
    input_refs: tuple[str, ...] = ()
    tool_call_refs: tuple[str, ...] = ()
    memory_context_refs: tuple[str, ...] = ()
    output_ref: str | None = None
    output_checksum: str | None = None
    artifact_refs: tuple[str, ...] = ()
    gate_results: tuple[Mapping[str, Any], ...] = ()
    budget_snapshot: Mapping[str, Any] = field(default_factory=dict)
    redaction_report: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    events: tuple[Mapping[str, Any], ...] = ()
    observed_at: datetime = field(default_factory=utc_now)
    schema_version: str = SUBAGENT_TRANSCRIPT_SCHEMA
    transcript_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SubAgentAttemptIdentity):
            raise TypeError("identity must be SubAgentAttemptIdentity")
        if self.schema_version != SUBAGENT_TRANSCRIPT_SCHEMA:
            raise HarnessValidationError("unsupported subagent transcript schema", code="subagent_transcript_schema_unsupported")
        object.__setattr__(self, "context_envelope_ref", _required(self.context_envelope_ref, "context_envelope_ref", max_length=2048))
        object.__setattr__(self, "input_refs", _refs(self.input_refs, "input_refs", allow_empty=False))
        object.__setattr__(self, "tool_call_refs", _refs(self.tool_call_refs, "tool_call_refs"))
        object.__setattr__(self, "memory_context_refs", _refs(self.memory_context_refs, "memory_context_refs"))
        object.__setattr__(self, "output_ref", _optional(self.output_ref, "output_ref", max_length=2048))
        if self.output_checksum is not None:
            object.__setattr__(self, "output_checksum", _checksum(self.output_checksum, "output_checksum"))
        object.__setattr__(self, "artifact_refs", _refs(self.artifact_refs, "artifact_refs"))
        object.__setattr__(self, "gate_results", tuple(_gate_evidence(item) for item in self.gate_results))
        object.__setattr__(self, "budget_snapshot", _mapping(self.budget_snapshot, "budget_snapshot"))
        object.__setattr__(self, "redaction_report", _mapping(self.redaction_report, "redaction_report"))
        object.__setattr__(self, "warnings", _bounded_codes(self.warnings, "warnings"))
        object.__setattr__(self, "errors", _bounded_codes(self.errors, "errors"))
        object.__setattr__(self, "events", tuple(_mapping(item, "events") for item in self.events))
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at, "observed_at"))
        object.__setattr__(self, "transcript_checksum", checksum_for(self.checksum_projection()))
        if len(stable_json_dumps(self.to_dict(include_checksum=False)).encode("utf-8")) > DEFAULT_MAX_TRANSCRIPT_BYTES:
            raise HarnessValidationError("subagent transcript exceeds size limit", code="subagent_transcript_size_exceeded")

    @property
    def transcript_id(self) -> str:
        return self.identity.transcript_id

    @property
    def invocation_id(self) -> str:
        return self.identity.invocation_id

    @property
    def parent_run_id(self) -> str:
        return self.identity.parent_run_id

    @property
    def child_run_id(self) -> str:
        return self.identity.child_run_id

    @property
    def subagent_id(self) -> str:
        return self.identity.subagent_id

    @property
    def ref(self) -> str:
        return f"subagent-transcript://v1/{self.identity.parent_run_id}/{self.transcript_id}"

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "context_envelope_ref": self.context_envelope_ref,
            "input_refs": list(self.input_refs),
            "tool_call_refs": list(self.tool_call_refs),
            "memory_context_refs": list(self.memory_context_refs),
            "output_ref": self.output_ref,
            "output_checksum": self.output_checksum,
            "artifact_refs": list(self.artifact_refs),
            "gate_results": to_jsonable(list(self.gate_results)),
            "budget_snapshot": to_jsonable(self.budget_snapshot),
            "redaction_report": to_jsonable(self.redaction_report),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "events": to_jsonable(list(self.events)),
            "observed_at": format_datetime(self.observed_at),
        }

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        payload = self.checksum_projection()
        if include_checksum:
            payload["transcript_checksum"] = self.transcript_checksum
        payload["transcript_id"] = self.transcript_id
        payload["ref"] = self.ref
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = dict(value)
        payload.pop("transcript_id", None)
        payload.pop("ref", None)
        supplied = _checksum(payload.pop("transcript_checksum", None), "transcript_checksum")
        raw_identity = payload.pop("identity", None)
        if not isinstance(raw_identity, Mapping):
            raise HarnessValidationError("transcript identity is required", code="subagent_transcript_invalid_payload")
        result = cls(identity=SubAgentAttemptIdentity.from_dict(raw_identity), **payload)
        _verify_checksum(result.checksum_projection(), supplied, "transcript_checksum")
        return result


def _bounded_codes(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise HarnessValidationError(f"{field_name} must be an array", code="subagent_transcript_invalid_codes")
    if len(values) > 128:
        raise HarnessValidationError(
            f"{field_name} exceeds its item limit",
            code="subagent_transcript_invalid_codes",
        )
    normalized = tuple(_required(str(value), field_name, max_length=128) for value in values)
    if any(_REASON_CODE_PATTERN.fullmatch(value) is None for value in normalized):
        raise HarnessValidationError(
            f"{field_name} must contain stable reason codes",
            code="subagent_transcript_invalid_codes",
        )
    return normalized


def _gate_evidence(value: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = _mapping(value, "gate_results")
    required = {
        "gate_id",
        "gate_version",
        "input_checksum",
        "passed",
        "reason_code",
        "evidence_checksum",
    }
    if set(evidence) != required:
        raise HarnessValidationError(
            "subagent gate evidence fields are invalid",
            code="subagent_transcript_gate_evidence_invalid",
        )
    gate_id = _required(evidence["gate_id"], "gate_id", max_length=128)
    gate_version = _required(evidence["gate_version"], "gate_version", max_length=32)
    input_checksum = _checksum(evidence["input_checksum"], "input_checksum")
    if not isinstance(evidence["passed"], bool):
        raise HarnessValidationError(
            "subagent gate evidence outcome must be boolean",
            code="subagent_transcript_gate_evidence_invalid",
        )
    reason_code = _bounded_codes((str(evidence["reason_code"]),), "reason_code")[0]
    supplied = _checksum(evidence["evidence_checksum"], "evidence_checksum")
    projection = {
        "gate_id": gate_id,
        "gate_version": gate_version,
        "input_checksum": input_checksum,
        "passed": evidence["passed"],
        "reason_code": reason_code,
    }
    _verify_checksum(projection, supplied, "evidence_checksum")
    return normalize_canonical_json(
        {**projection, "evidence_checksum": supplied},
        path="$.gate_results",
    )


@dataclass(frozen=True, slots=True)
class SubAgentTranscriptReceipt:
    transcript_ref: str
    transcript_checksum: str
    transcript_id: str
    invocation_id: str
    parent_run_id: str
    child_run_id: str
    task_instance_id: str
    attempt: int
    context_ref: str
    context_checksum: str
    output_ref: str
    output_checksum: str
    storage_revision: str
    committed_at: datetime
    schema_version: str = SUBAGENT_RECEIPT_SCHEMA
    receipt_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != SUBAGENT_RECEIPT_SCHEMA:
            raise HarnessValidationError("unsupported subagent receipt schema", code="subagent_transcript_schema_unsupported")
        for field_name in ("transcript_ref", "context_ref", "output_ref", "storage_revision"):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name, max_length=2048))
        for field_name in ("transcript_checksum", "context_checksum", "output_checksum"):
            object.__setattr__(self, field_name, _checksum(getattr(self, field_name), field_name))
        for field_name in ("transcript_id", "invocation_id", "parent_run_id", "child_run_id", "task_instance_id"):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        object.__setattr__(self, "attempt", _positive(self.attempt, "attempt"))
        object.__setattr__(self, "committed_at", _timestamp(self.committed_at, "committed_at"))
        object.__setattr__(self, "receipt_checksum", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transcript_ref": self.transcript_ref,
            "transcript_checksum": self.transcript_checksum,
            "transcript_id": self.transcript_id,
            "invocation_id": self.invocation_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "task_instance_id": self.task_instance_id,
            "attempt": self.attempt,
            "context_ref": self.context_ref,
            "context_checksum": self.context_checksum,
            "output_ref": self.output_ref,
            "output_checksum": self.output_checksum,
            "storage_revision": self.storage_revision,
            "committed_at": format_datetime(self.committed_at),
        }

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        payload = self.checksum_projection()
        if include_checksum:
            payload["receipt_checksum"] = self.receipt_checksum
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = dict(value)
        supplied = _checksum(payload.pop("receipt_checksum", None), "receipt_checksum")
        result = cls(**payload)
        _verify_checksum(result.checksum_projection(), supplied, "receipt_checksum")
        return result


@runtime_checkable
class SubAgentTranscriptStorePort(Protocol):
    def write(
        self,
        context: SubAgentContextEvidence,
        output: SubAgentOutputDocument,
        transcript: SubAgentTranscript,
    ) -> SubAgentTranscriptReceipt: ...

    def read(self, transcript_ref: str) -> SubAgentTranscript: ...

    def read_context(self, context_ref: str) -> SubAgentContextEvidence: ...

    def read_output(self, output_ref: str) -> SubAgentOutputDocument: ...

    def verify(self, receipt: SubAgentTranscriptReceipt) -> SubAgentTranscriptReceipt: ...

    def refs_for_parent(self, parent_run_id: str, *, limit: int = MAX_PARENT_QUERY) -> tuple[str, ...]: ...

    def find_by_identity(self, identity: SubAgentAttemptIdentity) -> SubAgentTranscriptReceipt | None: ...


class FakeSubAgentTranscriptStore:
    """Explicit test-only store implementing immutable bundle semantics."""

    is_durable = False

    def __init__(self) -> None:
        self.contexts: dict[str, SubAgentContextEvidence] = {}
        self.outputs: dict[str, SubAgentOutputDocument] = {}
        self.transcripts: dict[str, SubAgentTranscript] = {}
        self.receipts: dict[str, SubAgentTranscriptReceipt] = {}

    def write(self, context: SubAgentContextEvidence, output: SubAgentOutputDocument, transcript: SubAgentTranscript) -> SubAgentTranscriptReceipt:
        _validate_bundle_identity(context, output, transcript)
        existing = self.find_by_identity(transcript.identity)
        if existing is not None:
            if (
                self.contexts.get(existing.context_ref) != context
                or self.outputs.get(existing.output_ref) != output
                or self.transcripts.get(existing.transcript_ref) != transcript
            ):
                raise SubAgentTranscriptConflictError("subagent transcript identity already has different content", code="subagent_transcript_conflict")
            return existing
        committed_at = utc_now()
        receipt = SubAgentTranscriptReceipt(
            transcript_ref=transcript.ref,
            transcript_checksum=transcript.transcript_checksum,
            transcript_id=transcript.transcript_id,
            invocation_id=transcript.identity.invocation_id,
            parent_run_id=transcript.identity.parent_run_id,
            child_run_id=transcript.identity.child_run_id,
            task_instance_id=transcript.identity.task_instance_id,
            attempt=transcript.identity.attempt,
            context_ref=f"subagent-context://v1/{transcript.identity.parent_run_id}/{transcript.transcript_id}",
            context_checksum=context.context_checksum,
            output_ref=output.ref,
            output_checksum=output.output_checksum,
            storage_revision=f"memory:{transcript.transcript_id}",
            committed_at=committed_at,
        )
        self.contexts[receipt.context_ref] = context
        self.outputs[receipt.output_ref] = output
        self.transcripts[receipt.transcript_ref] = transcript
        self.receipts[receipt.transcript_ref] = receipt
        return receipt

    def read(self, transcript_ref: str) -> SubAgentTranscript:
        try:
            return self.transcripts[transcript_ref]
        except KeyError as exc:
            raise SubAgentTranscriptStoreError("subagent transcript was not found", code="subagent_transcript_not_found") from exc

    def read_context(self, context_ref: str) -> SubAgentContextEvidence:
        try:
            return self.contexts[context_ref]
        except KeyError as exc:
            raise SubAgentTranscriptStoreError("subagent context evidence was not found", code="subagent_context_not_found") from exc

    def read_output(self, output_ref: str) -> SubAgentOutputDocument:
        try:
            return self.outputs[output_ref]
        except KeyError as exc:
            raise SubAgentTranscriptStoreError("subagent output was not found", code="subagent_output_not_found") from exc

    def verify(self, receipt: SubAgentTranscriptReceipt) -> SubAgentTranscriptReceipt:
        if not isinstance(receipt, SubAgentTranscriptReceipt):
            raise TypeError("receipt must be SubAgentTranscriptReceipt")
        stored = self.receipts.get(receipt.transcript_ref)
        if stored != receipt:
            raise SubAgentTranscriptCorruptError("subagent receipt is not current", code="subagent_transcript_corrupt")
        context = self.read_context(receipt.context_ref)
        output = self.read_output(receipt.output_ref)
        transcript = self.read(receipt.transcript_ref)
        _validate_bundle_identity(context, output, transcript)
        identity = transcript.identity
        if (
            context.identity != identity
            or output.identity != identity
            or receipt.transcript_id != identity.transcript_id
            or receipt.invocation_id != identity.invocation_id
            or receipt.parent_run_id != identity.parent_run_id
            or receipt.child_run_id != identity.child_run_id
            or receipt.task_instance_id != identity.task_instance_id
            or receipt.attempt != identity.attempt
            or receipt.transcript_ref != transcript.ref
            or receipt.context_ref
            != f"subagent-context://v1/{identity.parent_run_id}/{identity.transcript_id}"
            or receipt.output_ref != output.ref
            or transcript.output_ref != output.ref
            or transcript.output_checksum != output.output_checksum
            or transcript.transcript_checksum != receipt.transcript_checksum
            or output.output_checksum != receipt.output_checksum
            or context.context_checksum != receipt.context_checksum
        ):
            raise SubAgentTranscriptCorruptError("subagent receipt checksum mismatch", code="subagent_transcript_checksum_mismatch")
        return receipt

    def refs_for_parent(self, parent_run_id: str, *, limit: int = MAX_PARENT_QUERY) -> tuple[str, ...]:
        parent = _required(parent_run_id, "parent_run_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > MAX_PARENT_QUERY:
            raise HarnessValidationError("transcript parent query limit is invalid", code="subagent_transcript_query_limit_invalid")
        refs = sorted(ref for ref, item in self.transcripts.items() if item.identity.parent_run_id == parent)
        return tuple(refs[:limit])

    def find_by_identity(self, identity: SubAgentAttemptIdentity) -> SubAgentTranscriptReceipt | None:
        if not isinstance(identity, SubAgentAttemptIdentity):
            raise TypeError("identity must be SubAgentAttemptIdentity")
        for receipt in self.receipts.values():
            if receipt.transcript_id != identity.transcript_id:
                continue
            transcript = self.transcripts.get(receipt.transcript_ref)
            if transcript is None:
                raise SubAgentTranscriptCorruptError(
                    "subagent identity lookup found a dangling receipt",
                    code="subagent_transcript_corrupt",
                )
            if transcript.identity == identity:
                return receipt
            raise SubAgentTranscriptCorruptError(
                "subagent identity lookup resolved a different attempt",
                code="subagent_transcript_identity_mismatch",
            )
        return None


def _validate_bundle_identity(context: SubAgentContextEvidence, output: SubAgentOutputDocument, transcript: SubAgentTranscript) -> None:
    if context.identity != output.identity or output.identity != transcript.identity:
        raise HarnessValidationError("subagent evidence identity mismatch", code="subagent_transcript_identity_mismatch")
    if transcript.output_ref is not None and transcript.output_ref != output.ref:
        raise HarnessValidationError("transcript output ref does not match output document", code="subagent_output_ref_mismatch")
    if transcript.output_checksum is not None and transcript.output_checksum != output.output_checksum:
        raise HarnessValidationError("transcript output checksum does not match output document", code="subagent_output_checksum_mismatch")
    if transcript.artifact_refs != output.artifact_refs:
        raise HarnessValidationError(
            "transcript artifact refs do not match output document",
            code="subagent_artifact_refs_mismatch",
        )


__all__ = [
    "DEFAULT_MAX_BUNDLE_BYTES",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_MAX_TRANSCRIPT_BYTES",
    "FakeSubAgentTranscriptStore",
    "SubAgentAttemptIdentity",
    "SubAgentContextEvidence",
    "SubAgentOutputDocument",
    "SubAgentTranscript",
    "SubAgentTranscriptConflictError",
    "SubAgentTranscriptCorruptError",
    "SubAgentTranscriptReceipt",
    "SubAgentTranscriptStoreError",
    "SubAgentTranscriptStorePort",
    "sanitize_subagent_payload",
]
