"""Durable v2 workflow checkpoint contract.

The active workflow writer uses this model after a durable event boundary has
been accepted. These types remain separate from ``WorkflowCheckpoint`` so a
legacy recorder count cannot be mistaken for a durable stream sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
import json
from typing import Any

from framework.agent.artifacts import validate_artifact_path_segment
from framework.events.canonical import normalize_canonical_json, thaw_canonical_json
from framework.shared.json import to_jsonable


CHECKPOINT_SCHEMA_VERSION_V2 = "workflow-checkpoint/v2"


def canonical_run_stream_id(run_id: str) -> str:
    normalized = validate_artifact_path_segment(
        _required_text(run_id, "run_id"),
        field="run_id",
    )
    return f"run:{normalized}"


@dataclass(frozen=True, slots=True)
class DurableWorkflowCheckpoint:
    checkpoint_id: str
    run_id: str
    workflow_id: str
    workflow_version: str
    current_step_ids: list[str]
    data_buffer_snapshot: dict[str, Any]
    stream_id: str
    last_durable_stream_sequence: int | None
    last_event_id: str | None
    step_results: dict[str, Any] = field(default_factory=dict)
    path: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _canonicalize_checkpoint_fields(self)
        _validate_boundary(
            run_id=self.run_id,
            stream_id=self.stream_id,
            sequence=self.last_durable_stream_sequence,
            event_id=self.last_event_id,
        )
        _validate_v2_metadata(self.metadata)

    @property
    def after_sequence(self) -> int | None:
        return self.last_durable_stream_sequence

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "current_step_ids": list(self.current_step_ids),
            "data_buffer_snapshot": to_jsonable(self.data_buffer_snapshot),
            "stream_id": self.stream_id,
            "last_durable_stream_sequence": self.last_durable_stream_sequence,
            "last_event_id": self.last_event_id,
            "step_results": to_jsonable(self.step_results),
            "path": list(self.path),
            "created_at": _format_datetime(self.created_at),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DurableWorkflowCheckpoint:
        _require_keys(
            payload,
            {
                "stream_id",
                "last_durable_stream_sequence",
                "last_event_id",
            },
        )
        return cls(
            checkpoint_id=_required_text(payload.get("checkpoint_id"), "checkpoint_id"),
            run_id=_required_text(payload.get("run_id"), "run_id"),
            workflow_id=_required_text(payload.get("workflow_id"), "workflow_id"),
            workflow_version=_required_text(
                payload.get("workflow_version"),
                "workflow_version",
            ),
            current_step_ids=[
                str(step_id) for step_id in payload.get("current_step_ids", [])
            ],
            data_buffer_snapshot=dict(payload.get("data_buffer_snapshot") or {}),
            stream_id=_required_text(payload.get("stream_id"), "stream_id"),
            last_durable_stream_sequence=_optional_positive_int(
                payload.get("last_durable_stream_sequence"),
                "last_durable_stream_sequence",
            ),
            last_event_id=_optional_text(payload.get("last_event_id")),
            step_results=dict(payload.get("step_results") or {}),
            path=[str(step_id) for step_id in payload.get("path", [])],
            created_at=_parse_datetime(payload.get("created_at")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointV2Envelope:
    checkpoint_id: str
    run_id: str
    workflow_id: str
    workflow_version: str
    current_step_ids: list[str]
    data_buffer_snapshot: dict[str, Any]
    step_results: dict[str, Any]
    path: list[str]
    stream_id: str
    last_durable_stream_sequence: int | None
    last_event_id: str | None
    manifest_hash: str | None
    checksum: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = field(default=CHECKPOINT_SCHEMA_VERSION_V2, init=False)

    def __post_init__(self) -> None:
        _canonicalize_checkpoint_fields(self)
        _validate_boundary(
            run_id=self.run_id,
            stream_id=self.stream_id,
            sequence=self.last_durable_stream_sequence,
            event_id=self.last_event_id,
        )
        if not self.checksum:
            raise ValueError("checksum is required")
        _parse_datetime(self.created_at)
        _validate_v2_metadata(self.metadata)

    @property
    def after_sequence(self) -> int | None:
        return self.last_durable_stream_sequence


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointRecoveryCursor:
    stream_id: str
    after_sequence: int | None
    last_event_id: str | None
    boundary_verified: bool = False
    reconciled_through_sequence: int | None = None
    reconciled_event_id: str | None = None
    recovered_transition_type: str | None = None
    recovered_workflow_status: str | None = None

    def __post_init__(self) -> None:
        sequence = _optional_positive_int(self.after_sequence, "after_sequence")
        event_id = _optional_text(self.last_event_id)
        if (sequence is None) != (event_id is None):
            raise ValueError("after_sequence and last_event_id must both be set or absent")
        object.__setattr__(self, "stream_id", _required_text(self.stream_id, "stream_id"))
        object.__setattr__(self, "after_sequence", sequence)
        object.__setattr__(self, "last_event_id", event_id)
        if not isinstance(self.boundary_verified, bool):
            raise ValueError("boundary_verified must be a boolean")
        if sequence is not None and not self.boundary_verified:
            raise ValueError(
                "non-empty recovery cursor requires verified boundary event identity"
            )
        reconciled_sequence = _optional_positive_int(
            self.reconciled_through_sequence,
            "reconciled_through_sequence",
        )
        reconciled_event_id = _optional_text(self.reconciled_event_id)
        if (reconciled_sequence is None) != (reconciled_event_id is None):
            raise ValueError(
                "reconciled_through_sequence and reconciled_event_id must both be set or absent"
            )
        if reconciled_sequence is not None and (
            sequence is not None and reconciled_sequence <= sequence
        ):
            raise ValueError(
                "reconciled transition must be after the checkpoint boundary"
            )
        transition_type = _optional_text(self.recovered_transition_type)
        workflow_status = _optional_text(self.recovered_workflow_status)
        if (transition_type is None) != (workflow_status is None):
            raise ValueError(
                "recovered transition type and workflow status must both be set or absent"
            )
        if transition_type is not None and reconciled_sequence is None:
            raise ValueError("recovered transition requires a reconciled event boundary")
        object.__setattr__(
            self,
            "reconciled_through_sequence",
            reconciled_sequence,
        )
        object.__setattr__(self, "reconciled_event_id", reconciled_event_id)
        object.__setattr__(self, "recovered_transition_type", transition_type)
        object.__setattr__(self, "recovered_workflow_status", workflow_status)

    @property
    def effective_after_sequence(self) -> int | None:
        return self.reconciled_through_sequence or self.after_sequence

    def should_apply(self, stream_sequence: int) -> bool:
        sequence = _positive_int(stream_sequence, "stream_sequence")
        effective_boundary = self.effective_after_sequence
        return effective_boundary is None or sequence > effective_boundary


def durable_envelope_from_checkpoint(
    checkpoint: DurableWorkflowCheckpoint,
    *,
    manifest_hash: str | None = None,
) -> WorkflowCheckpointV2Envelope:
    envelope = WorkflowCheckpointV2Envelope(
        checkpoint_id=checkpoint.checkpoint_id,
        run_id=checkpoint.run_id,
        workflow_id=checkpoint.workflow_id,
        workflow_version=checkpoint.workflow_version,
        current_step_ids=list(checkpoint.current_step_ids),
        data_buffer_snapshot=dict(checkpoint.data_buffer_snapshot),
        step_results=dict(checkpoint.step_results),
        path=list(checkpoint.path),
        stream_id=checkpoint.stream_id,
        last_durable_stream_sequence=checkpoint.last_durable_stream_sequence,
        last_event_id=checkpoint.last_event_id,
        manifest_hash=manifest_hash,
        checksum="pending",
        created_at=_format_datetime(checkpoint.created_at),
        metadata=dict(checkpoint.metadata),
    )
    return attach_durable_checkpoint_checksum(envelope)


def durable_envelope_to_checkpoint(
    envelope: WorkflowCheckpointV2Envelope,
) -> DurableWorkflowCheckpoint:
    if not verify_durable_checkpoint_checksum(envelope):
        raise ValueError("checkpoint checksum is invalid")
    return DurableWorkflowCheckpoint(
        checkpoint_id=envelope.checkpoint_id,
        run_id=envelope.run_id,
        workflow_id=envelope.workflow_id,
        workflow_version=envelope.workflow_version,
        current_step_ids=list(envelope.current_step_ids),
        data_buffer_snapshot=dict(envelope.data_buffer_snapshot),
        stream_id=envelope.stream_id,
        last_durable_stream_sequence=envelope.last_durable_stream_sequence,
        last_event_id=envelope.last_event_id,
        step_results=dict(envelope.step_results),
        path=list(envelope.path),
        created_at=_parse_datetime(envelope.created_at),
        metadata=dict(envelope.metadata),
    )


def durable_envelope_to_payload(
    envelope: WorkflowCheckpointV2Envelope,
) -> dict[str, Any]:
    return {
        "checkpoint_id": envelope.checkpoint_id,
        "schema_version": CHECKPOINT_SCHEMA_VERSION_V2,
        "run_id": envelope.run_id,
        "workflow_id": envelope.workflow_id,
        "workflow_version": envelope.workflow_version,
        "current_step_ids": list(envelope.current_step_ids),
        "data_buffer_snapshot": to_jsonable(envelope.data_buffer_snapshot),
        "step_results": to_jsonable(envelope.step_results),
        "path": list(envelope.path),
        "stream_id": envelope.stream_id,
        "last_durable_stream_sequence": envelope.last_durable_stream_sequence,
        "last_event_id": envelope.last_event_id,
        "manifest_hash": envelope.manifest_hash,
        "checksum": envelope.checksum,
        "created_at": envelope.created_at,
        "metadata": to_jsonable(envelope.metadata),
    }


def durable_envelope_from_payload(
    payload: dict[str, Any],
) -> WorkflowCheckpointV2Envelope:
    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION_V2:
        raise ValueError(
            "unsupported durable checkpoint schema_version: "
            f"{payload.get('schema_version')}"
        )
    _require_keys(
        payload,
        {
            "stream_id",
            "last_durable_stream_sequence",
            "last_event_id",
        },
    )
    return WorkflowCheckpointV2Envelope(
        checkpoint_id=_required_text(payload.get("checkpoint_id"), "checkpoint_id"),
        run_id=_required_text(payload.get("run_id"), "run_id"),
        workflow_id=_required_text(payload.get("workflow_id"), "workflow_id"),
        workflow_version=_required_text(
            payload.get("workflow_version"),
            "workflow_version",
        ),
        current_step_ids=[
            str(step_id) for step_id in payload.get("current_step_ids", [])
        ],
        data_buffer_snapshot=dict(payload.get("data_buffer_snapshot") or {}),
        step_results=dict(payload.get("step_results") or {}),
        path=[str(step_id) for step_id in payload.get("path", [])],
        stream_id=_required_text(payload.get("stream_id"), "stream_id"),
        last_durable_stream_sequence=_optional_positive_int(
            payload.get("last_durable_stream_sequence"),
            "last_durable_stream_sequence",
        ),
        last_event_id=_optional_text(payload.get("last_event_id")),
        manifest_hash=_optional_text(payload.get("manifest_hash")),
        checksum=_required_text(payload.get("checksum"), "checksum"),
        created_at=_required_text(payload.get("created_at"), "created_at"),
        metadata=dict(payload.get("metadata") or {}),
    )


def durable_checkpoint_checksum_payload(
    envelope: WorkflowCheckpointV2Envelope,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in durable_envelope_to_payload(envelope).items()
        if key != "checksum"
    }


def compute_durable_checkpoint_checksum(payload: dict[str, Any]) -> str:
    normalized = normalize_canonical_json(payload, path="$.checkpoint")
    encoded = json.dumps(
        thaw_canonical_json(normalized),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def attach_durable_checkpoint_checksum(
    envelope: WorkflowCheckpointV2Envelope,
) -> WorkflowCheckpointV2Envelope:
    checksum = compute_durable_checkpoint_checksum(
        durable_checkpoint_checksum_payload(envelope)
    )
    return replace(envelope, checksum=checksum)


def verify_durable_checkpoint_checksum(
    envelope: WorkflowCheckpointV2Envelope,
) -> bool:
    expected = compute_durable_checkpoint_checksum(
        durable_checkpoint_checksum_payload(envelope)
    )
    return compare_digest(envelope.checksum, expected)


def recovery_cursor_from_durable_checkpoint(
    envelope: WorkflowCheckpointV2Envelope,
    *,
    boundary_event_stream_id: str | None = None,
    boundary_event_sequence: int | None = None,
    boundary_event_id: str | None = None,
) -> WorkflowCheckpointRecoveryCursor:
    if not verify_durable_checkpoint_checksum(envelope):
        raise ValueError("checkpoint checksum is invalid")
    checkpoint_sequence = envelope.last_durable_stream_sequence
    checkpoint_event_id = envelope.last_event_id
    if checkpoint_sequence is not None:
        actual_stream_id = _optional_text(boundary_event_stream_id)
        actual_sequence = _optional_positive_int(
            boundary_event_sequence,
            "boundary_event_sequence",
        )
        actual_event_id = _optional_text(boundary_event_id)
        if (
            actual_stream_id != envelope.stream_id
            or actual_sequence != checkpoint_sequence
            or actual_event_id != checkpoint_event_id
        ):
            raise ValueError(
                "checkpoint boundary event does not match authoritative stream history"
            )
    elif (
        boundary_event_stream_id is not None
        or boundary_event_sequence is not None
        or boundary_event_id is not None
    ):
        raise ValueError("empty checkpoint cannot have a boundary event")
    return WorkflowCheckpointRecoveryCursor(
        stream_id=envelope.stream_id,
        after_sequence=checkpoint_sequence,
        last_event_id=checkpoint_event_id,
        boundary_verified=True,
    )


def _validate_boundary(
    *,
    run_id: str,
    stream_id: str,
    sequence: int | None,
    event_id: str | None,
) -> None:
    normalized_run_id = _required_text(run_id, "run_id")
    normalized_stream_id = _required_text(stream_id, "stream_id")
    expected_stream_id = canonical_run_stream_id(normalized_run_id)
    if normalized_stream_id != expected_stream_id:
        raise ValueError(
            "checkpoint stream_id does not match authoritative run stream: "
            f"{normalized_stream_id} != {expected_stream_id}"
        )
    normalized_sequence = _optional_positive_int(
        sequence,
        "last_durable_stream_sequence",
    )
    normalized_event_id = _optional_text(event_id)
    if (normalized_sequence is None) != (normalized_event_id is None):
        raise ValueError(
            "last_durable_stream_sequence and last_event_id must both be set or absent"
        )


def _validate_v2_metadata(metadata: dict[str, Any]) -> None:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    forbidden = {"event_offset", "legacy_event_offset"}.intersection(metadata)
    if forbidden:
        raise ValueError(
            "legacy offsets are valid only inside metadata.legacy_import: "
            + ", ".join(sorted(forbidden))
        )


def _canonicalize_checkpoint_fields(checkpoint: Any) -> None:
    for field_name in (
        "checkpoint_id",
        "run_id",
        "workflow_id",
        "workflow_version",
        "stream_id",
    ):
        value = _required_text(getattr(checkpoint, field_name), field_name)
        object.__setattr__(checkpoint, field_name, value)
    object.__setattr__(
        checkpoint,
        "last_event_id",
        _optional_text(checkpoint.last_event_id),
    )
    if hasattr(checkpoint, "manifest_hash"):
        object.__setattr__(
            checkpoint,
            "manifest_hash",
            _optional_text(checkpoint.manifest_hash),
        )
        object.__setattr__(
            checkpoint,
            "checksum",
            _required_text(checkpoint.checksum, "checksum"),
        )
    object.__setattr__(
        checkpoint,
        "current_step_ids",
        [str(step_id) for step_id in checkpoint.current_step_ids],
    )
    object.__setattr__(checkpoint, "path", [str(step_id) for step_id in checkpoint.path])
    for field_name in ("data_buffer_snapshot", "step_results", "metadata"):
        normalized = normalize_canonical_json(
            getattr(checkpoint, field_name),
            path=f"$.checkpoint.{field_name}",
        )
        thawed = thaw_canonical_json(normalized)
        if not isinstance(thawed, dict):
            raise ValueError(f"{field_name} must be an object")
        object.__setattr__(checkpoint, field_name, thawed)
    if isinstance(getattr(checkpoint, "created_at"), datetime):
        object.__setattr__(checkpoint, "created_at", _parse_datetime(checkpoint.created_at))
    else:
        object.__setattr__(
            checkpoint,
            "created_at",
            _format_datetime(_parse_datetime(checkpoint.created_at)),
        )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional text cannot be empty")
    return value.strip()


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive 1-based integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("created_at is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return _parse_datetime(value).isoformat().replace("+00:00", "Z")


def _require_keys(payload: dict[str, Any], required: set[str]) -> None:
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("checkpoint is missing required field(s): " + ", ".join(missing))


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION_V2",
    "DurableWorkflowCheckpoint",
    "WorkflowCheckpointRecoveryCursor",
    "WorkflowCheckpointV2Envelope",
    "attach_durable_checkpoint_checksum",
    "canonical_run_stream_id",
    "compute_durable_checkpoint_checksum",
    "durable_checkpoint_checksum_payload",
    "durable_envelope_from_checkpoint",
    "durable_envelope_from_payload",
    "durable_envelope_to_checkpoint",
    "durable_envelope_to_payload",
    "recovery_cursor_from_durable_checkpoint",
    "verify_durable_checkpoint_checksum",
]
