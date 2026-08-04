from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias
from uuid import uuid4

from framework.agent.artifacts import (
    ArtifactPathError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.workflow.checkpoint.checksum import verify_checkpoint_checksum
from framework.workflow.checkpoint.durable import (
    CHECKPOINT_SCHEMA_VERSION_V2,
    DurableWorkflowCheckpoint,
    durable_envelope_from_checkpoint,
    durable_envelope_from_payload,
    durable_envelope_to_checkpoint,
    durable_envelope_to_payload,
)
from framework.workflow.checkpoint.envelope import (
    CHECKPOINT_SCHEMA_VERSION,
    envelope_from_payload,
    envelope_to_checkpoint,
)
from framework.workflow.checkpoint.model import WorkflowCheckpoint

if TYPE_CHECKING:
    from framework.workflow.checkpoint.durable import WorkflowCheckpointV2Envelope
    from framework.workflow.checkpoint.migration import (
        DurableCheckpointMigrationRegistry,
        LegacyCheckpointOffsetSemantics,
    )


StoredWorkflowCheckpoint: TypeAlias = WorkflowCheckpoint | DurableWorkflowCheckpoint


class WorkflowCheckpointStore(Protocol):
    def save_checkpoint(self, checkpoint: StoredWorkflowCheckpoint) -> Path:
        ...

    def get_latest_checkpoint(self, run_id: str) -> StoredWorkflowCheckpoint | None:
        ...


class CheckpointNotFoundError(FileNotFoundError):
    pass


class LocalJsonCheckpointStore:
    def __init__(self, root: str | Path = ".newsroom/checkpoints") -> None:
        self.root = Path(root)

    def save_checkpoint(self, checkpoint: StoredWorkflowCheckpoint) -> Path:
        _validate_id(checkpoint.run_id, "run_id")
        _validate_id(checkpoint.checkpoint_id, "checkpoint_id")
        path = self._checkpoint_path(checkpoint.run_id, checkpoint.checkpoint_id)
        payload = _checkpoint_to_payload(checkpoint)
        _write_json_atomic(path, payload)
        return path

    def get_latest_checkpoint(self, run_id: str) -> StoredWorkflowCheckpoint | None:
        checkpoints = self.list_checkpoints(run_id)
        if not checkpoints:
            return None
        return sorted(
            checkpoints,
            key=lambda checkpoint: (checkpoint.created_at, checkpoint.checkpoint_id),
            reverse=True,
        )[0]

    def list_checkpoints(self, run_id: str) -> list[StoredWorkflowCheckpoint]:
        validated_run_id = _validate_id(run_id, "run_id")
        run_dir = resolve_artifact_descendant(
            self.root,
            validated_run_id,
            field="run_id",
        )
        if not run_dir.exists():
            return []
        checkpoints = []
        for candidate in sorted(run_dir.glob("*.json")):
            path = resolve_artifact_descendant(
                run_dir,
                candidate.name,
                field="checkpoint_path",
            )
            payload = _read_json_object(path)
            checkpoints.append(_checkpoint_from_payload(payload))
        return checkpoints

    def get_checkpoint(
        self,
        run_id: str,
        checkpoint_id: str,
    ) -> StoredWorkflowCheckpoint:
        path = self._checkpoint_path(run_id, checkpoint_id)
        if not path.exists():
            raise CheckpointNotFoundError(f"checkpoint not found: {run_id}/{checkpoint_id}")
        return _checkpoint_from_payload(_read_json_object(path))

    def import_durable_checkpoint(
        self,
        run_id: str,
        checkpoint_id: str,
        *,
        migration_registry: DurableCheckpointMigrationRegistry,
        source_semantics: LegacyCheckpointOffsetSemantics,
    ) -> WorkflowCheckpointV2Envelope:
        """Explicitly import one legacy file through a recorded v2 mapping.

        Active v2 files already load as ``DurableWorkflowCheckpoint`` through
        the normal read methods. This opt-in API exists only for v0/v1 history,
        where a raw ``event_offset`` cannot become a stream sequence directly.
        """

        path = self._checkpoint_path(run_id, checkpoint_id)
        if not path.exists():
            raise CheckpointNotFoundError(
                f"checkpoint not found: {run_id}/{checkpoint_id}"
            )
        payload = _read_json_object(path)
        return migration_registry.migrate_to_v2(
            payload,
            source_semantics=source_semantics,
        )

    def _checkpoint_path(self, run_id: str, checkpoint_id: str) -> Path:
        validated_run_id = _validate_id(run_id, "run_id")
        validated_checkpoint_id = _validate_id(checkpoint_id, "checkpoint_id")
        return resolve_artifact_descendant(
            self.root,
            validated_run_id,
            f"{validated_checkpoint_id}.json",
            field="checkpoint_path",
        )


def _validate_id(value: str, label: str) -> str:
    try:
        return validate_artifact_path_segment(value, field=label)
    except ArtifactPathError as exc:
        raise ArtifactPathError(f"invalid {label}: {value}") from exc


def _checkpoint_to_payload(
    checkpoint: StoredWorkflowCheckpoint,
) -> dict[str, Any]:
    if isinstance(checkpoint, DurableWorkflowCheckpoint):
        return durable_envelope_to_payload(
            durable_envelope_from_checkpoint(checkpoint)
        )
    if isinstance(checkpoint, WorkflowCheckpoint):
        return checkpoint.to_dict()
    raise TypeError(
        "checkpoint must be WorkflowCheckpoint or DurableWorkflowCheckpoint"
    )


def _checkpoint_from_payload(payload: dict[str, Any]) -> StoredWorkflowCheckpoint:
    schema_version = payload.get("schema_version")
    if schema_version == CHECKPOINT_SCHEMA_VERSION_V2:
        return durable_envelope_to_checkpoint(
            durable_envelope_from_payload(payload)
        )
    if schema_version == CHECKPOINT_SCHEMA_VERSION:
        envelope = envelope_from_payload(payload)
        if not verify_checkpoint_checksum(envelope):
            raise ValueError("checkpoint checksum is invalid")
        return envelope_to_checkpoint(envelope)
    if schema_version is not None:
        raise ValueError(f"unsupported checkpoint schema_version: {schema_version}")
    if {
        "stream_id",
        "last_durable_stream_sequence",
        "last_event_id",
    }.intersection(payload):
        raise ValueError("durable checkpoint is missing schema_version")
    return WorkflowCheckpoint.from_dict(payload)


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("checkpoint payload must be an object")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary_path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


