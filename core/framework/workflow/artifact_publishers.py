from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Protocol

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.specs import WorkflowSpec, WorkflowStatus
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


class ArtifactPublisherRegistry:
    def __init__(
        self,
        publishers: Iterable[WorkflowArtifactPublisher] | None = None,
    ) -> None:
        self._publishers: dict[str, WorkflowArtifactPublisher] = {}
        for publisher in publishers or ():
            self.register(publisher)

    def register(self, publisher: WorkflowArtifactPublisher) -> None:
        publisher_id = _publisher_id(publisher)
        if publisher_id in self._publishers:
            raise ValueError(f"artifact publisher is already registered: {publisher_id}")
        self._publishers[publisher_id] = publisher

    def get(self, publisher_id: str) -> WorkflowArtifactPublisher:
        return self._publishers[publisher_id]

    def registered_publishers(self) -> list[WorkflowArtifactPublisher]:
        return list(self._publishers.values())

    def supported_publishers(
        self,
        context: ArtifactPublishContext,
    ) -> list[WorkflowArtifactPublisher]:
        return [
            publisher
            for publisher in self._publishers.values()
            if publisher.supports(context)
        ]

    def publish_all(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        artifact_refs: list[ArtifactRef] = []
        for publisher in self.supported_publishers(context):
            artifact_refs.extend(publisher.publish(context))
        return artifact_refs


def _publisher_id(publisher: WorkflowArtifactPublisher) -> str:
    publisher_id = getattr(publisher, "publisher_id", None)
    if not isinstance(publisher_id, str) or not publisher_id.strip():
        raise ValueError("artifact publisher must define a non-empty publisher_id")
    return publisher_id.strip()
