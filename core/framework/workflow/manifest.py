from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol

from core.framework.specs import StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow.artifacts import ArtifactRef, redact_metadata, utc_now_iso


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

_SENSITIVE_MANIFEST_METADATA_KEYS = {
    "metadata",
    "artifact_metadata",
    "operations",
    "metrics",
}

_LEGACY_MANIFEST_OPTIONAL_DEFAULTS: dict[str, Any] = {
    "artifact_refs": [],
    "checkpoints": [],
    "operations": [],
    "runner_versions": {},
    "step_artifacts": [],
}


class RunManifestError(ValueError):
    """Raised when a workflow run manifest would become invalid."""


@dataclass
class WorkflowRunManifest:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowStatus
    created_at: str
    updated_at: str
    graph_hash: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    data_buffer_snapshot_hash: str | None = None
    runner_versions: dict[str, str] = field(default_factory=dict)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    event_log_path: str | None = None
    resumed_from_checkpoint_id: str | None = None
    parent_run_id: str | None = None
    child_run_ids: list[str] = field(default_factory=list)
    manifest_hash: str | None = None

    def __post_init__(self) -> None:
        self.status = WorkflowStatus(self.status)
        self.runner_versions = {str(key): str(value) for key, value in self.runner_versions.items()}
        self.artifacts = [
            artifact if isinstance(artifact, ArtifactRef) else ArtifactRef.from_dict(artifact)
            for artifact in self.artifacts
        ]
        self.operations = [
            redact_metadata(dict(operation))
            for operation in self.operations
        ]
        self.metrics = redact_metadata(dict(self.metrics))
        self.manifest_hash = manifest_hash(self)

    def add_artifact(self, artifact_ref: ArtifactRef) -> None:
        self.artifacts.append(artifact_ref)
        self.touch()

    def add_checkpoint(self, checkpoint_id: str) -> None:
        self.checkpoints.append(str(checkpoint_id))
        self.touch()

    def add_operation(self, operation_record: dict[str, Any]) -> None:
        self.operations.append(redact_metadata(dict(operation_record)))
        self.touch()

    def update_metrics(self, metrics: dict[str, Any]) -> None:
        self.metrics.update(redact_metadata(dict(metrics)))
        self.touch()

    def touch(self) -> None:
        self.updated_at = utc_now_iso()
        self.manifest_hash = manifest_hash(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "graph_hash": self.graph_hash,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "data_buffer_snapshot_hash": self.data_buffer_snapshot_hash,
            "runner_versions": dict(self.runner_versions),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "checkpoints": list(self.checkpoints),
            "operations": [redact_metadata(dict(operation)) for operation in self.operations],
            "metrics": redact_metadata(dict(self.metrics)),
            "event_log_path": self.event_log_path,
            "resumed_from_checkpoint_id": self.resumed_from_checkpoint_id,
            "parent_run_id": self.parent_run_id,
            "child_run_ids": list(self.child_run_ids),
            "manifest_hash": self.manifest_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowRunManifest:
        manifest = cls(
            run_id=str(payload["run_id"]),
            workflow_id=str(payload["workflow_id"]),
            workflow_version=str(payload["workflow_version"]),
            status=WorkflowStatus(str(payload["status"])),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            graph_hash=_optional_str(payload.get("graph_hash")),
            input_hash=_optional_str(payload.get("input_hash")),
            output_hash=_optional_str(payload.get("output_hash")),
            data_buffer_snapshot_hash=_optional_str(payload.get("data_buffer_snapshot_hash")),
            runner_versions={
                str(key): str(value)
                for key, value in dict(payload.get("runner_versions") or {}).items()
            },
            artifacts=[
                ArtifactRef.from_dict(item)
                for item in payload.get("artifacts", [])
                if isinstance(item, dict)
            ],
            checkpoints=[str(item) for item in payload.get("checkpoints", [])],
            operations=[
                redact_metadata(dict(item))
                for item in payload.get("operations", [])
                if isinstance(item, dict)
            ],
            metrics=redact_metadata(dict(payload.get("metrics") or {})),
            event_log_path=_optional_str(payload.get("event_log_path")),
            resumed_from_checkpoint_id=_optional_str(payload.get("resumed_from_checkpoint_id")),
            parent_run_id=_optional_str(payload.get("parent_run_id")),
            child_run_ids=[str(item) for item in payload.get("child_run_ids", [])],
        )
        stored_hash = payload.get("manifest_hash")
        if stored_hash is not None:
            manifest.manifest_hash = str(stored_hash)
        return manifest


class ManifestStore(Protocol):
    def write(self, manifest: WorkflowRunManifest) -> None:
        ...

    def read(self, run_id: str) -> WorkflowRunManifest:
        ...

    def update(self, manifest: WorkflowRunManifest) -> None:
        ...

    def exists(self, run_id: str) -> bool:
        ...


class JsonManifestStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write(self, manifest: WorkflowRunManifest) -> None:
        self._manifest_path(manifest.run_id).parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path(manifest.run_id).write_text(
            stable_json_dumps(manifest.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def read(self, run_id: str) -> WorkflowRunManifest:
        path = self._manifest_path(run_id)
        if not path.exists():
            raise RunManifestError(f"manifest does not exist for run_id: {run_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowRunManifest.from_dict(normalize_legacy_run_manifest(payload))

    def update(self, manifest: WorkflowRunManifest) -> None:
        manifest.touch()
        self.write(manifest)

    def exists(self, run_id: str) -> bool:
        return self._manifest_path(run_id).exists()

    def _manifest_path(self, run_id: str) -> Path:
        return self.root / run_id / "manifest.json"


@dataclass(frozen=True)
class StepRunnerManifestItem:
    step_id: str
    step_type: StepType
    runner_id: str
    runner_version: str
    implementation: str | None = None
    side_effect_level: str | None = None
    supports_checkpoint: bool = False
    supports_resume: bool = False
    supports_timeout: bool = False
    supports_retry: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "runner_id": self.runner_id,
            "runner_version": self.runner_version,
            "implementation": self.implementation,
            "side_effect_level": self.side_effect_level,
            "supports_checkpoint": self.supports_checkpoint,
            "supports_resume": self.supports_resume,
            "supports_timeout": self.supports_timeout,
            "supports_retry": self.supports_retry,
        }


@dataclass(frozen=True)
class WorkflowRunnerManifest:
    workflow_id: str
    runners: list[StepRunnerManifestItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "runners": [item.to_dict() for item in self.runners],
        }


def build_runner_manifest(
    workflow: WorkflowSpec,
    registry: Any,
) -> WorkflowRunnerManifest:
    items: list[StepRunnerManifestItem] = []
    for step in workflow.steps:
        runner = registry.resolve(step)
        if runner is None:
            continue
        capability = getattr(runner, "capability", None)
        if capability is None:
            continue
        items.append(
            StepRunnerManifestItem(
                step_id=step.step_id,
                step_type=step.step_type,
                runner_id=capability.runner_id,
                runner_version=capability.version,
                implementation=step.implementation,
                side_effect_level=getattr(capability.side_effect_level, "value", str(capability.side_effect_level)),
                supports_checkpoint=capability.supports_checkpoint,
                supports_resume=capability.supports_resume,
                supports_timeout=capability.supports_timeout,
                supports_retry=capability.supports_retry,
            )
        )
    return WorkflowRunnerManifest(workflow_id=workflow.workflow_id, runners=items)


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
        "artifact_refs": [],
        "runner_versions": {},
        "checkpoints": [],
        "operations": [],
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
    register_manifest_artifact_ref(manifest, artifact_ref)
    return artifact_path


def register_manifest_artifact_ref(manifest: dict[str, Any], artifact_ref: Any) -> None:
    payload = artifact_ref.to_dict() if hasattr(artifact_ref, "to_dict") else dict(artifact_ref)
    normalized = _normalize_artifact_ref_payload(payload)
    embedded = None
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("workflow_artifact_ref"), dict):
        embedded = _normalize_artifact_ref_payload(dict(metadata["workflow_artifact_ref"]))
    artifact_refs = manifest.setdefault("artifact_refs", [])
    if not isinstance(artifact_refs, list):
        raise RunManifestError("manifest artifact_refs must be a list")
    for item in [embedded or normalized]:
        artifact_id = item.get("artifact_id")
        if artifact_id is None or not any(
            existing.get("artifact_id") == artifact_id
            for existing in artifact_refs
            if isinstance(existing, dict)
        ):
            artifact_refs.append(item)


def update_manifest_runner_versions(manifest: dict[str, Any], runner_manifest: WorkflowRunnerManifest) -> None:
    runner_versions = manifest.setdefault("runner_versions", {})
    if not isinstance(runner_versions, dict):
        raise RunManifestError("manifest runner_versions must be an object")
    for item in runner_manifest.runners:
        runner_versions[item.step_id] = item.runner_version


def add_manifest_checkpoint(manifest: dict[str, Any], checkpoint_id: str) -> None:
    checkpoints = manifest.setdefault("checkpoints", [])
    if not isinstance(checkpoints, list):
        raise RunManifestError("manifest checkpoints must be a list")
    checkpoints.append(str(checkpoint_id))


def add_manifest_operation(manifest: dict[str, Any], operation_record: dict[str, Any]) -> None:
    operations = manifest.setdefault("operations", [])
    if not isinstance(operations, list):
        raise RunManifestError("manifest operations must be a list")
    operations.append(redact_metadata(dict(operation_record)))


def update_manifest_metrics(manifest: dict[str, Any], metrics: dict[str, Any]) -> None:
    existing = manifest.setdefault("metrics", {})
    if not isinstance(existing, dict):
        raise RunManifestError("manifest metrics must be an object")
    existing.update(redact_metadata(dict(metrics)))


def manifest_hash(manifest: WorkflowRunManifest | dict[str, Any]) -> str:
    if isinstance(manifest, WorkflowRunManifest):
        payload = manifest.to_dict()
    else:
        payload = _redacted_manifest_payload(dict(manifest))
    payload.pop("manifest_hash", None)
    return stable_hash(payload)


def stable_hash(value: Any) -> str:
    raw = stable_json_dumps(value)
    return sha256(raw.encode("utf-8")).hexdigest()


def stable_json_dumps(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=None if indent is not None else (",", ":"),
        default=str,
        indent=indent,
    )


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


def normalize_legacy_run_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(manifest)
    for field, default in _LEGACY_MANIFEST_OPTIONAL_DEFAULTS.items():
        normalized.setdefault(field, list(default) if isinstance(default, list) else dict(default) if isinstance(default, dict) else default)
    if normalized.get("schema_version") is None:
        normalized["schema_version"] = RUN_MANIFEST_SCHEMA_VERSION
    if "finished_at" not in normalized:
        normalized["finished_at"] = None
    return normalized


def validate_run_manifest(
    manifest: dict[str, Any],
    *,
    require_terminal_artifact: bool = False,
) -> None:
    manifest = normalize_legacy_run_manifest(manifest)
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
    _validate_artifact_metadata(manifest, artifacts)
    _validate_artifact_refs(manifest)


def _normalize_manifest_artifact_path(relative_path: str) -> str:
    path = Path(str(relative_path).replace("\\", "/"))
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


def _validate_artifact_metadata(
    manifest: dict[str, Any],
    artifacts: dict[str, str],
) -> None:
    raw_metadata = manifest.get("artifact_metadata")
    if raw_metadata is None:
        return
    if not isinstance(raw_metadata, dict):
        raise RunManifestError("run manifest artifact_metadata must be an object")
    for artifact_key in artifacts:
        metadata = raw_metadata.get(artifact_key)
        if not isinstance(metadata, dict):
            raise RunManifestError(
                f"run manifest artifact metadata is missing for: {artifact_key}"
            )
        checksum = metadata.get("checksum")
        content_type = metadata.get("content_type")
        size_bytes = metadata.get("size_bytes")
        if not isinstance(checksum, str) or not checksum:
            raise RunManifestError(
                f"run manifest artifact metadata checksum is required for: {artifact_key}"
            )
        if not isinstance(content_type, str) or not content_type:
            raise RunManifestError(
                f"run manifest artifact metadata content_type is required for: {artifact_key}"
            )
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise RunManifestError(
                f"run manifest artifact metadata size_bytes is required for: {artifact_key}"
            )


def _validate_artifact_refs(manifest: dict[str, Any]) -> None:
    raw_refs = manifest.get("artifact_refs")
    if raw_refs is None:
        return
    if not isinstance(raw_refs, list):
        raise RunManifestError("run manifest artifact_refs must be a list")
    required = {
        "artifact_id",
        "artifact_type",
        "key",
        "uri",
        "content_hash",
        "size_bytes",
        "created_by_step_id",
        "status",
    }
    for item in raw_refs:
        if not isinstance(item, dict):
            raise RunManifestError("run manifest artifact_refs entries must be objects")
        missing = sorted(required - set(item))
        if missing:
            raise RunManifestError(
                "run manifest artifact_ref missing required field(s): "
                + ", ".join(missing)
            )


def _normalize_artifact_ref_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "uri" in payload and "content_hash" in payload:
        normalized = dict(payload)
    else:
        normalized = {
            "artifact_id": payload.get("artifact_id"),
            "artifact_type": payload.get("artifact_type"),
            "key": payload.get("key") or payload.get("metadata", {}).get("artifact_key") or payload.get("artifact_id"),
            "uri": payload.get("uri") or payload.get("path"),
            "content_hash": payload.get("content_hash") or payload.get("checksum"),
            "size_bytes": payload.get("size_bytes"),
            "media_type": payload.get("media_type") or payload.get("content_type"),
            "created_by_step_id": payload.get("created_by_step_id") or payload.get("step_id") or "workflow",
            "created_at": payload.get("created_at") or utc_now_iso(),
            "status": payload.get("status") or "published",
            "metadata": payload.get("metadata") or {},
        }
    normalized["metadata"] = redact_metadata(dict(normalized.get("metadata") or {}))
    return normalized


def _redacted_manifest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    for key in _SENSITIVE_MANIFEST_METADATA_KEYS:
        if key in redacted and isinstance(redacted[key], dict):
            redacted[key] = redact_metadata(redacted[key])
        elif key in redacted and isinstance(redacted[key], list):
            redacted[key] = [
                redact_metadata(item) if isinstance(item, dict) else item
                for item in redacted[key]
            ]
    return redacted


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
