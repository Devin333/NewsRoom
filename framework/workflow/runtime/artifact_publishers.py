from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Protocol

from framework.artifacts import (
    ArtifactManager,
    resolve_artifact_descendant,
    validate_relative_artifact_path,
)
from framework.specs import WorkflowSpec, WorkflowStatus
from framework.workflow.runtime.manifest import (
    manifest_hash,
    register_manifest_artifact,
    register_manifest_artifact_ref,
    validate_run_manifest,
)
from framework.workflow.runtime.result import StepOutcome, WorkflowError
from framework.artifacts import ArtifactRef


class ArtifactPublishPhase(str, Enum):
    START = "start"
    TERMINAL = "terminal"


@dataclass
class ArtifactPublishContext:
    phase: ArtifactPublishPhase
    run_id: str
    workflow: WorkflowSpec
    profile: str
    status: WorkflowStatus
    request: dict[str, Any]
    output: dict[str, Any]
    manifest: dict[str, Any]
    artifact_manager: ArtifactManager
    step_results: dict[str, StepOutcome]
    path: list[str]
    error: WorkflowError | None = None
    current_step_ids: list[str] | None = None
    checkpoint_ids: list[str] | None = None
    initial_buffer_snapshot: Any | None = None
    final_buffer_snapshot: Any | None = None
    buffer_diff: Any | None = None
    metrics_payload: dict[str, Any] | None = None
    redaction_report: dict[str, Any] | None = None
    events_path: Path | None = None

    def __post_init__(self) -> None:
        self.phase = ArtifactPublishPhase(self.phase)
        self.status = WorkflowStatus(self.status)


class WorkflowArtifactPublisher(Protocol):
    publisher_id: str

    def supports(self, context: ArtifactPublishContext) -> bool:
        ...

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        ...


class RuntimeArtifactPublisher:
    publisher_id = "runtime"

    def supports(self, context: ArtifactPublishContext) -> bool:
        return context.phase in {
            ArtifactPublishPhase.START,
            ArtifactPublishPhase.TERMINAL,
        }

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        if context.phase == ArtifactPublishPhase.START:
            return self._publish_start(context)
        return self._publish_terminal(context)

    def _publish_start(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs = [
            _write_json_artifact(context, "request", "request.json", context.request),
            _write_json_artifact(context, "workflow_spec", "workflow_spec.json", context.workflow),
            _write_json_artifact(
                context,
                "workflow_version",
                "workflow_version.json",
                _workflow_version_payload(context.workflow),
            ),
            _write_json_artifact(
                context,
                "data_buffer_initial",
                "data_buffer.initial.json",
                _artifact_payload(context.initial_buffer_snapshot),
            ),
        ]
        return refs

    def _publish_terminal(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        if context.status == WorkflowStatus.SUCCEEDED:
            refs.append(_write_json_artifact(context, "output", "output.json", context.output))
        elif context.status in {WorkflowStatus.PAUSED, WorkflowStatus.WAITING_FOR_HUMAN}:
            refs.append(_write_json_artifact(context, "pause", "pause.json", _pause_payload(context)))
        else:
            refs.append(_write_json_artifact(context, "error", "error.json", context.error))

        metrics_payload = _required_payload(context.metrics_payload, "metrics_payload")
        metrics_payload["artifact_count"] = len(context.manifest.get("artifacts") or {})
        context.metrics_payload = metrics_payload

        refs.extend(
            [
                _write_json_artifact(
                    context,
                    "data_buffer_snapshot",
                    "data_buffer_snapshot.json",
                    context.output,
                ),
                _write_json_artifact(
                    context,
                    "data_buffer_final",
                    "data_buffer.final.json",
                    _artifact_payload(context.final_buffer_snapshot, fallback=context.output),
                ),
                _write_json_artifact(
                    context,
                    "data_buffer_diff",
                    "data_buffer.diff.json",
                    _artifact_payload(context.buffer_diff),
                ),
                _write_json_artifact(
                    context,
                    "step_results",
                    "step_results.json",
                    {
                        step_id: outcome.to_dict()
                        for step_id, outcome in context.step_results.items()
                    },
                ),
                _write_json_artifact(
                    context,
                    "metrics",
                    "metrics.json",
                    metrics_payload,
                ),
                _write_json_artifact(
                    context,
                    "redaction_report",
                    "redaction_report.json",
                    _required_payload(context.redaction_report, "redaction_report"),
                ),
            ]
        )

        context.manifest["event_count"] = context.metrics_payload["event_count"]
        context.manifest["metrics"] = context.metrics_payload
        context.manifest["redaction_report"] = context.redaction_report
        context.manifest["manifest_hash"] = manifest_hash(context.manifest)
        refs.append(_write_manifest_artifact(context))
        return refs


class WorkflowArtifactPublisherRegistry:
    def __init__(
        self,
        publishers: Iterable[WorkflowArtifactPublisher] | None = None,
    ) -> None:
        self._publishers: list[WorkflowArtifactPublisher] = []
        for publisher in publishers or ():
            self.register(publisher)

    def register(self, publisher: WorkflowArtifactPublisher) -> None:
        publisher_id = _publisher_id(publisher)
        if any(_publisher_id(item) == publisher_id for item in self._publishers):
            raise ValueError(f"artifact publisher already registered: {publisher_id}")
        self._publishers.append(publisher)

    def get(self, publisher_id: str) -> WorkflowArtifactPublisher:
        for publisher in self._publishers:
            if _publisher_id(publisher) == publisher_id:
                return publisher
        raise KeyError(publisher_id)

    def registered_publishers(self) -> list[WorkflowArtifactPublisher]:
        return list(self._publishers)

    def supported_publishers(
        self,
        context: ArtifactPublishContext,
    ) -> list[WorkflowArtifactPublisher]:
        return [
            publisher
            for publisher in self._publishers
            if publisher.supports(context)
        ]

    def publish_all(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        artifact_refs: list[ArtifactRef] = []
        seen_artifact_ids: set[str] = set()
        for publisher in self.supported_publishers(context):
            for artifact_ref in publisher.publish(context):
                if artifact_ref.artifact_id in seen_artifact_ids:
                    raise ValueError(
                        f"duplicate artifact id published: {artifact_ref.artifact_id}"
                    )
                seen_artifact_ids.add(artifact_ref.artifact_id)
                artifact_refs.append(artifact_ref)
        return artifact_refs


ArtifactPublisherRegistry = WorkflowArtifactPublisherRegistry


def register_manifest_artifact_once(
    manifest: dict[str, Any],
    artifact_key: str,
    relative_path: str,
) -> None:
    artifacts = manifest.get("artifacts")
    existing = artifacts.get(artifact_key) if isinstance(artifacts, dict) else None
    existing_path = _manifest_artifact_path(existing)
    if existing_path is not None and existing_path != relative_path:
        raise ValueError(
            f"manifest artifact key conflict: {artifact_key} "
            f"{existing_path} != {relative_path}"
        )
    register_manifest_artifact(manifest, artifact_key, relative_path)


def _write_json_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    payload: Any,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_json(context.run_id, relative_path, payload)
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type="application/json",
    )


def _write_manifest_artifact(context: ArtifactPublishContext) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, "manifest", "manifest.json")
    context.manifest["manifest_hash"] = manifest_hash(context.manifest)
    context.artifact_manager.write_json(context.run_id, "manifest.json", context.manifest)
    _populate_artifact_metadata(context.manifest, context.artifact_manager.run_dir(context.run_id))
    context.manifest["manifest_hash"] = manifest_hash(context.manifest)
    validate_run_manifest(context.manifest, require_terminal_artifact=True)
    path = context.artifact_manager.write_json(context.run_id, "manifest.json", context.manifest)
    manifest_ref = _artifact_ref(
        context,
        artifact_id="manifest",
        artifact_type="manifest",
        relative_path="manifest.json",
        path=path,
        content_type="application/json",
    )
    register_manifest_artifact_ref(context.manifest, manifest_ref)
    context.manifest["manifest_hash"] = manifest_hash(context.manifest)
    path = context.artifact_manager.write_json(context.run_id, "manifest.json", context.manifest)
    return _artifact_ref(
        context,
        artifact_id="manifest",
        artifact_type="manifest",
        relative_path="manifest.json",
        path=path,
        content_type="application/json",
    )


def _artifact_ref(
    context: ArtifactPublishContext,
    *,
    artifact_id: str,
    artifact_type: str,
    relative_path: str,
    path: Path,
    content_type: str,
) -> ArtifactRef:
    normalized_relative_path = validate_relative_artifact_path(
        relative_path,
        field="artifact_path",
    )
    data = path.read_bytes()
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=context.run_id,
        artifact_type=artifact_type,
        path=normalized_relative_path,
        content_type=content_type,
        size_bytes=len(data),
        checksum=sha256(data).hexdigest(),
        redacted=True,
        metadata={
            "artifact_key": artifact_id,
            "workflow_id": context.workflow.workflow_id,
            "workflow_version": context.workflow.version,
            "phase": context.phase.value,
        },
    )


def _pause_payload(context: ArtifactPublishContext) -> dict[str, Any]:
    checkpoint_ids = context.checkpoint_ids or []
    return {
        "status": context.status.value,
        "path": list(context.path),
        "current_step_ids": list(context.current_step_ids or []),
        "latest_checkpoint_id": checkpoint_ids[-1] if checkpoint_ids else None,
    }


def _artifact_payload(value: Any, *, fallback: Any | None = None) -> Any:
    if value is None:
        return fallback
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return value


def _required_payload(value: dict[str, Any] | None, field_name: str) -> dict[str, Any]:
    if value is None:
        raise ValueError(f"{field_name} is required for terminal runtime artifact publishing")
    return value


def _workflow_version_payload(workflow: WorkflowSpec) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "workflow_version": workflow.version,
        "name": workflow.name,
        "description": workflow.description,
        "trigger": workflow.trigger.to_dict() if workflow.trigger else None,
        "metadata": dict(workflow.metadata),
    }


def _populate_artifact_metadata(manifest: dict[str, Any], run_dir: Path) -> None:
    artifacts = manifest.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return
    metadata = manifest.setdefault("artifact_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        manifest["artifact_metadata"] = metadata
    for artifact_key, relative_path in sorted(artifacts.items()):
        relative = _manifest_artifact_path(relative_path)
        if relative is None:
            continue
        normalized_relative = validate_relative_artifact_path(
            relative,
            field=f"manifest_artifact_path[{artifact_key}]",
        )
        path = resolve_artifact_descendant(
            run_dir,
            normalized_relative,
            field=f"manifest_artifact_path[{artifact_key}]",
        )
        try:
            data = path.read_bytes()
        except OSError:
            continue
        key = str(artifact_key)
        metadata[key] = {
            "checksum": "pending" if key == "manifest" else sha256(data).hexdigest(),
            "content_type": _content_type_for_artifact_path(normalized_relative),
            "size_bytes": len(data),
        }
    manifest_metadata = metadata.get("manifest")
    if not isinstance(manifest_metadata, dict):
        manifest_metadata = {}
    metadata["manifest"] = {
        "checksum": "pending",
        "content_type": manifest_metadata.get("content_type") or "application/json",
        "size_bytes": (
            manifest_metadata.get("size_bytes")
            if isinstance(manifest_metadata.get("size_bytes"), int)
            and manifest_metadata["size_bytes"] >= 0
            else 0
        ),
    }


def _content_type_for_artifact_path(relative_path: str) -> str:
    suffix = str(relative_path).rsplit(".", 1)[-1].casefold() if "." in relative_path else ""
    if suffix == "json":
        return "application/json"
    if suffix == "jsonl":
        return "application/x-ndjson"
    if suffix == "md":
        return "text/markdown"
    if suffix == "txt":
        return "text/plain"
    return "application/octet-stream"


def _publisher_id(publisher: WorkflowArtifactPublisher) -> str:
    publisher_id = getattr(publisher, "publisher_id", None)
    if not isinstance(publisher_id, str) or not publisher_id.strip():
        raise ValueError("artifact publisher must define a non-empty publisher_id")
    return publisher_id.strip()


def _manifest_artifact_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        path = value.get("path")
        return str(path) if path is not None else None
    return str(value)

