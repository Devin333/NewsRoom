from __future__ import annotations

from pathlib import Path
from typing import Any

from core.framework.specs import WorkflowSpec, WorkflowStatus


RUN_MANIFEST_SCHEMA_VERSION = "newsroom.workflow_run_manifest.v1"

REQUIRED_RUN_ARTIFACTS: dict[str, str] = {
    "request": "request.json",
    "workflow_spec": "workflow_spec.json",
    "workflow_version": "workflow_version.json",
    "events": "events.jsonl",
    "manifest": "manifest.json",
    "data_buffer_snapshot": "data_buffer_snapshot.json",
    "data_buffer_initial": "data_buffer.initial.json",
    "data_buffer_final": "data_buffer.final.json",
    "data_buffer_diff": "data_buffer.diff.json",
    "step_results": "step_results.json",
    "metrics": "metrics.json",
    "redaction_report": "redaction_report.json",
}

_REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "run_id",
    "workflow_id",
    "workflow_version",
    "profile",
    "status",
    "started_at",
    "finished_at",
    "path",
    "steps",
    "artifacts",
)


class RunManifestError(ValueError):
    """Raised when a workflow run manifest would become invalid."""


def build_run_manifest(
    *,
    run_id: str,
    workflow: WorkflowSpec,
    profile: str,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "workflow_id": workflow.workflow_id,
        "workflow_version": workflow.version,
        "profile": profile,
        "status": WorkflowStatus.RUNNING.value,
        "started_at": started_at,
        "finished_at": None,
        "path": [],
        "steps": {},
        "artifacts": dict(REQUIRED_RUN_ARTIFACTS),
    }


def register_manifest_artifact(
    manifest: dict[str, Any],
    artifact_key: str,
    relative_path: str,
) -> str:
    key = str(artifact_key).strip()
    if not key:
        raise RunManifestError("manifest artifact key is required")
    normalized_path = _normalize_manifest_artifact_path(relative_path)
    artifacts = manifest.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise RunManifestError("manifest artifacts must be an object")
    artifacts[key] = normalized_path
    return normalized_path


def register_manifest_step_artifact(manifest: dict[str, Any], artifact_ref: Any) -> str:
    step_artifacts = manifest.setdefault("step_artifacts", [])
    if not isinstance(step_artifacts, list):
        raise RunManifestError("manifest step_artifacts must be a list")
    payload = artifact_ref.to_dict() if hasattr(artifact_ref, "to_dict") else dict(artifact_ref)
    path = _artifact_ref_value(artifact_ref, "path")
    if path is None:
        raise RunManifestError("manifest step artifact path is required")
    artifact_path = register_manifest_artifact(
        manifest,
        manifest_step_artifact_key(artifact_ref),
        str(path),
    )
    step_artifacts.append(payload)
    return artifact_path


def manifest_step_artifact_key(artifact_ref: Any) -> str:
    step_id = _artifact_ref_value(artifact_ref, "step_id") or "workflow"
    artifact_type = _artifact_ref_value(artifact_ref, "artifact_type")
    artifact_id = _artifact_ref_value(artifact_ref, "artifact_id")
    if artifact_type is None or artifact_id is None:
        raise RunManifestError("manifest step artifact requires artifact_type and artifact_id")
    return f"step.{step_id}.{artifact_type}.{artifact_id}"


def manifest_schema_version(manifest: dict[str, Any]) -> str | None:
    value = manifest.get("schema_version")
    if value is None:
        return None
    return str(value)


def validate_run_manifest(
    manifest: dict[str, Any],
    *,
    require_terminal_artifact: bool = False,
) -> None:
    missing_fields = [field for field in _REQUIRED_MANIFEST_FIELDS if field not in manifest]
    if missing_fields:
        raise RunManifestError(
            "run manifest is missing required field(s): " + ", ".join(missing_fields)
        )
    schema_version = manifest_schema_version(manifest)
    if schema_version != RUN_MANIFEST_SCHEMA_VERSION:
        raise RunManifestError(f"unsupported run manifest schema_version: {schema_version}")
    _validate_manifest_status(manifest.get("status"))
    _validate_manifest_shape(manifest)
    artifacts = _validated_manifest_artifacts(manifest)
    missing_artifacts = [
        key for key in REQUIRED_RUN_ARTIFACTS if key not in artifacts
    ]
    if missing_artifacts:
        raise RunManifestError(
            "run manifest is missing required artifact(s): " + ", ".join(missing_artifacts)
        )
    if require_terminal_artifact:
        _validate_terminal_artifact(manifest, artifacts)
    _validate_step_artifacts(manifest, artifacts)


def _normalize_manifest_artifact_path(relative_path: str) -> str:
    path = Path(str(relative_path))
    if path.is_absolute() or ".." in path.parts:
        raise RunManifestError(
            f"manifest artifact path must be relative to the run directory: {relative_path}"
        )
    normalized = path.as_posix()
    if not normalized or normalized == ".":
        raise RunManifestError("manifest artifact path is required")
    return normalized


def _artifact_ref_value(artifact_ref: Any, name: str) -> Any:
    if isinstance(artifact_ref, dict):
        return artifact_ref.get(name)
    return getattr(artifact_ref, name, None)


def _validate_manifest_status(status: Any) -> None:
    try:
        WorkflowStatus(str(status))
    except ValueError as exc:
        raise RunManifestError(f"unsupported run manifest status: {status}") from exc


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    for field in ("run_id", "workflow_id", "workflow_version", "profile", "started_at"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise RunManifestError(f"run manifest field must be a non-empty string: {field}")
    if manifest.get("finished_at") is not None and not isinstance(manifest["finished_at"], str):
        raise RunManifestError("run manifest finished_at must be a string or null")
    if not isinstance(manifest.get("path"), list):
        raise RunManifestError("run manifest path must be a list")
    if not isinstance(manifest.get("steps"), dict):
        raise RunManifestError("run manifest steps must be an object")


def _validated_manifest_artifacts(manifest: dict[str, Any]) -> dict[str, str]:
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, dict):
        raise RunManifestError("run manifest artifacts must be an object")
    artifacts: dict[str, str] = {}
    for key, value in raw_artifacts.items():
        artifact_key = str(key).strip()
        if not artifact_key:
            raise RunManifestError("run manifest artifact key is required")
        if not isinstance(value, str):
            raise RunManifestError(
                f"run manifest artifact path must be a string: {artifact_key}"
            )
        artifacts[artifact_key] = _normalize_manifest_artifact_path(value)
    return artifacts


def _validate_terminal_artifact(
    manifest: dict[str, Any],
    artifacts: dict[str, str],
) -> None:
    status = WorkflowStatus(str(manifest["status"]))
    if status == WorkflowStatus.SUCCEEDED:
        required_key = "output"
    elif status in {WorkflowStatus.PAUSED, WorkflowStatus.WAITING_FOR_HUMAN}:
        required_key = "pause"
    elif status in {
        WorkflowStatus.FAILED,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.BUDGET_EXCEEDED,
        WorkflowStatus.CANCELLED,
    }:
        required_key = "error"
    else:
        return
    if required_key not in artifacts:
        raise RunManifestError(
            f"run manifest status {status.value} requires artifact: {required_key}"
        )


def _validate_step_artifacts(
    manifest: dict[str, Any],
    artifacts: dict[str, str],
) -> None:
    raw_step_artifacts = manifest.get("step_artifacts")
    if raw_step_artifacts is None:
        return
    if not isinstance(raw_step_artifacts, list):
        raise RunManifestError("run manifest step_artifacts must be a list")
    for item in raw_step_artifacts:
        if not isinstance(item, dict):
            raise RunManifestError("run manifest step_artifacts entries must be objects")
        artifact_key = manifest_step_artifact_key(item)
        path = item.get("path")
        if path is None:
            raise RunManifestError("run manifest step artifact path is required")
        normalized_path = _normalize_manifest_artifact_path(str(path))
        if artifacts.get(artifact_key) != normalized_path:
            raise RunManifestError(
                f"run manifest step artifact is missing artifact map entry: {artifact_key}"
            )
