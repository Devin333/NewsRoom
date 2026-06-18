"""Checkpoint envelope conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.workflow.checkpoint.model import WorkflowCheckpoint

CHECKPOINT_SCHEMA_VERSION = "workflow-checkpoint/v1"
CHECKPOINT_SCHEMA_VERSION_V0 = "workflow-checkpoint/v0"
CHECKPOINT_ENVELOPE_METADATA_KEY = "checkpoint_envelope"
__all__ = [
    "CHECKPOINT_ENVELOPE_METADATA_KEY",
    "CHECKPOINT_SCHEMA_VERSION",
    "CHECKPOINT_SCHEMA_VERSION_V0",
    "WorkflowCheckpointEnvelope",
    "envelope_from_checkpoint",
    "envelope_from_payload",
    "envelope_to_checkpoint",
    "envelope_to_payload",
]


@dataclass(frozen=True)
class WorkflowCheckpointEnvelope:
    checkpoint_id: str
    schema_version: str
    run_id: str
    workflow_id: str
    workflow_version: str
    current_step_ids: list[str]
    data_buffer_snapshot: dict[str, Any]
    step_results: dict[str, Any]
    path: list[str]
    manifest_hash: str | None
    checksum: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("schema_version is required")
        if not self.checksum:
            raise ValueError("checksum is required")


def envelope_from_checkpoint(
    checkpoint: WorkflowCheckpoint,
    *,
    manifest_hash: str | None = None,
) -> WorkflowCheckpointEnvelope:
    stored_envelope = _stored_envelope_metadata(checkpoint.metadata)
    actual_manifest_hash = (
        manifest_hash
        if manifest_hash is not None
        else _optional_str(stored_envelope.get("manifest_hash"))
    )
    stored_checksum = _optional_str(stored_envelope.get("checksum"))
    envelope = WorkflowCheckpointEnvelope(
        checkpoint_id=checkpoint.checkpoint_id,
        schema_version=_optional_str(stored_envelope.get("schema_version"))
        or CHECKPOINT_SCHEMA_VERSION,
        run_id=checkpoint.run_id,
        workflow_id=checkpoint.workflow_id,
        workflow_version=checkpoint.workflow_version,
        current_step_ids=list(checkpoint.current_step_ids),
        data_buffer_snapshot=dict(checkpoint.data_buffer_snapshot),
        step_results=dict(checkpoint.step_results),
        path=list(checkpoint.path),
        manifest_hash=actual_manifest_hash,
        checksum=stored_checksum or "pending",
        created_at=_datetime_to_string(checkpoint.created_at),
        metadata={
            **dict(checkpoint.metadata),
            "event_offset": checkpoint.event_offset,
        },
    )
    if stored_checksum:
        return envelope
    from framework.workflow.checkpoint.checksum import attach_checkpoint_checksum

    return attach_checkpoint_checksum(envelope)


def envelope_to_payload(envelope: WorkflowCheckpointEnvelope) -> dict[str, Any]:
    return {
        "checkpoint_id": envelope.checkpoint_id,
        "schema_version": envelope.schema_version,
        "run_id": envelope.run_id,
        "workflow_id": envelope.workflow_id,
        "workflow_version": envelope.workflow_version,
        "current_step_ids": list(envelope.current_step_ids),
        "data_buffer_snapshot": dict(envelope.data_buffer_snapshot),
        "step_results": dict(envelope.step_results),
        "path": list(envelope.path),
        "manifest_hash": envelope.manifest_hash,
        "checksum": envelope.checksum,
        "created_at": envelope.created_at,
        "metadata": dict(envelope.metadata),
    }


def envelope_to_checkpoint(envelope: WorkflowCheckpointEnvelope) -> WorkflowCheckpoint:
    event_offset = _event_offset_from_metadata(envelope.metadata)
    metadata = {
        str(key): value
        for key, value in envelope.metadata.items()
        if key != "event_offset"
    }
    runtime_only = metadata.get("runtime_only")
    if not isinstance(runtime_only, dict):
        runtime_only = {}
    else:
        runtime_only = dict(runtime_only)
    runtime_only[CHECKPOINT_ENVELOPE_METADATA_KEY] = {
        "schema_version": envelope.schema_version,
        "manifest_hash": envelope.manifest_hash,
        "checksum": envelope.checksum,
    }
    metadata["runtime_only"] = runtime_only
    return WorkflowCheckpoint(
        checkpoint_id=envelope.checkpoint_id,
        run_id=envelope.run_id,
        workflow_id=envelope.workflow_id,
        workflow_version=envelope.workflow_version,
        current_step_ids=list(envelope.current_step_ids),
        data_buffer_snapshot=dict(envelope.data_buffer_snapshot),
        step_results=dict(envelope.step_results),
        path=list(envelope.path),
        event_offset=event_offset,
        created_at=_parse_datetime(envelope.created_at),
        metadata=metadata,
    )


def envelope_from_payload(payload: dict[str, Any]) -> WorkflowCheckpointEnvelope:
    return WorkflowCheckpointEnvelope(
        checkpoint_id=str(payload["checkpoint_id"]),
        schema_version=str(payload["schema_version"]),
        run_id=str(payload["run_id"]),
        workflow_id=str(payload["workflow_id"]),
        workflow_version=str(payload["workflow_version"]),
        current_step_ids=[str(step_id) for step_id in payload.get("current_step_ids", [])],
        data_buffer_snapshot=dict(payload.get("data_buffer_snapshot") or {}),
        step_results=dict(payload.get("step_results") or {}),
        path=[str(step_id) for step_id in payload.get("path", [])],
        manifest_hash=_optional_str(payload.get("manifest_hash")),
        checksum=str(payload["checksum"]),
        created_at=str(payload["created_at"]),
        metadata=dict(payload.get("metadata") or {}),
    )


def _stored_envelope_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    runtime_only = metadata.get("runtime_only")
    if not isinstance(runtime_only, dict):
        return {}
    envelope_metadata = runtime_only.get(CHECKPOINT_ENVELOPE_METADATA_KEY)
    if not isinstance(envelope_metadata, dict):
        return {}
    return dict(envelope_metadata)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _event_offset_from_metadata(metadata: dict[str, Any]) -> int:
    try:
        return int(metadata.get("event_offset", 0))
    except (TypeError, ValueError):
        return 0


def _datetime_to_string(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
