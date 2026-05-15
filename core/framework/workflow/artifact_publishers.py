from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Protocol

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.specs import WorkflowSpec, WorkflowStatus
from core.framework.workflow.manifest import register_manifest_artifact
from core.framework.workflow.result import StepOutcome, WorkflowError
from storage.artifacts import ArtifactRef


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
