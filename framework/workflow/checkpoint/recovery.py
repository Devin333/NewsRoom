"""Partial checkpoint artifact recovery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.workflow.checkpoint.envelope import WorkflowCheckpointEnvelope

__all__ = [
    "PartialArtifactRecoveryReport",
    "inspect_checkpoint_artifacts",
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
    checkpoint: WorkflowCheckpointEnvelope,
    manifest: dict[str, Any] | None,
    artifact_root: Path,
    strict: bool,
) -> PartialArtifactRecoveryReport:
    missing_required: list[str] = []
    missing_optional: list[str] = []
    recovered: list[str] = []
    warnings: list[str] = []

    run_dir = Path(artifact_root) / checkpoint.run_id
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
                if (run_dir / relative_path).exists():
                    recovered.append(str(artifact_key))
                    continue
                if _required_artifact_key(str(artifact_key)):
                    missing_required.append(str(artifact_key))
                else:
                    missing_optional.append(str(artifact_key))
                    warnings.append(f"optional artifact is missing: {artifact_key}")
        events_path = run_dir / "events.jsonl"
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


def _artifact_manifest_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("path")
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _required_artifact_key(artifact_key: str) -> bool:
    return artifact_key in {"data_buffer_snapshot", "manifest"} or artifact_key.endswith(
        (".input", ".output")
    )
