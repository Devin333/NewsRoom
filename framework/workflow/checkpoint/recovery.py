"""Partial checkpoint artifact recovery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.artifacts import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.events.ports import EventReaderPort
from framework.workflow.checkpoint.durable import (
    WorkflowCheckpointRecoveryCursor,
    WorkflowCheckpointV2Envelope,
    recovery_cursor_from_durable_checkpoint,
)
from framework.workflow.checkpoint.envelope import WorkflowCheckpointEnvelope

__all__ = [
    "PartialArtifactRecoveryReport",
    "inspect_checkpoint_artifacts",
    "verified_checkpoint_recovery_cursor",
]


@dataclass(frozen=True)
class PartialArtifactRecoveryReport:
    recoverable: bool
    missing_required_artifacts: list[str] = field(default_factory=list)
    missing_optional_artifacts: list[str] = field(default_factory=list)
    recovered_artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recoverable": self.recoverable,
            "missing_required_artifacts": list(self.missing_required_artifacts),
            "missing_optional_artifacts": list(self.missing_optional_artifacts),
            "recovered_artifacts": list(self.recovered_artifacts),
            "warnings": list(self.warnings),
        }


def inspect_checkpoint_artifacts(
    *,
    checkpoint: WorkflowCheckpointEnvelope | WorkflowCheckpointV2Envelope,
    manifest: dict[str, Any] | None,
    artifact_root: Path,
    strict: bool,
) -> PartialArtifactRecoveryReport:
    missing_required: list[str] = []
    missing_optional: list[str] = []
    recovered: list[str] = []
    warnings: list[str] = []

    validated_run_id = validate_artifact_path_segment(checkpoint.run_id, field="run_id")
    run_dir = resolve_artifact_descendant(
        artifact_root,
        validated_run_id,
        field="run_id",
    )
    if manifest is None:
        if strict:
            missing_required.append("manifest.json")
        else:
            missing_optional.append("manifest.json")
            warnings.append("manifest.json is missing")
    else:
        artifacts = manifest.get("artifacts") or {}
        if isinstance(artifacts, dict):
            for artifact_key, artifact_value in sorted(artifacts.items()):
                relative_path = _artifact_manifest_path(artifact_value)
                if relative_path is None:
                    continue
                path = resolve_artifact_descendant(
                    run_dir,
                    relative_path,
                    field=f"manifest_artifact_path[{artifact_key}]",
                )
                if path.exists():
                    recovered.append(str(artifact_key))
                    continue
                if _required_artifact_key(str(artifact_key)):
                    missing_required.append(str(artifact_key))
                else:
                    missing_optional.append(str(artifact_key))
                    warnings.append(f"optional artifact is missing: {artifact_key}")
        events_path = resolve_artifact_descendant(
            run_dir,
            "events.jsonl",
            field="events_path",
        )
        if not events_path.exists():
            missing_optional.append("events")
            warnings.append("events.jsonl is missing")

    if checkpoint.data_buffer_snapshot:
        recovered.append("checkpoint.data_buffer_snapshot")
    else:
        missing_required.append("data_buffer_snapshot")

    return PartialArtifactRecoveryReport(
        recoverable=not missing_required,
        missing_required_artifacts=sorted(set(missing_required)),
        missing_optional_artifacts=sorted(set(missing_optional)),
        recovered_artifacts=sorted(set(recovered)),
        warnings=warnings,
    )


def verified_checkpoint_recovery_cursor(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    reader: EventReaderPort,
) -> WorkflowCheckpointRecoveryCursor:
    """Verify the v2 boundary against durable history before resuming after it."""

    sequence = checkpoint.last_durable_stream_sequence
    event_id = checkpoint.last_event_id
    if sequence is None:
        return recovery_cursor_from_durable_checkpoint(checkpoint)
    if event_id is None:
        raise ValueError("durable checkpoint boundary event_id is required")

    boundary = reader.get_event(event_id)
    if boundary is None:
        raise ValueError("checkpoint boundary event is missing from durable history")
    boundary.verify_integrity()
    if boundary.business_context.run_id != checkpoint.run_id:
        raise ValueError("checkpoint boundary event run_id does not match checkpoint")
    return recovery_cursor_from_durable_checkpoint(
        checkpoint,
        boundary_event_stream_id=boundary.stream_id,
        boundary_event_sequence=boundary.stream_sequence,
        boundary_event_id=boundary.event_id,
    )


def _artifact_manifest_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("path")
    if value is None:
        return None
    return validate_relative_artifact_path(str(value), field="manifest_artifact_path")


def _required_artifact_key(artifact_key: str) -> bool:
    return artifact_key in {"data_buffer_snapshot", "manifest"} or artifact_key.endswith(
        (".input", ".output")
    )
