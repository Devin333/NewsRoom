from __future__ import annotations

from collections.abc import Callable

from framework.workflow.runtime.artifact_publishers import ArtifactPublishContext
from infrastructure.storage.artifacts import ArtifactRef


ArtifactSectionPublisher = Callable[[ArtifactPublishContext], list[ArtifactRef]]


def publish_daily_artifact_sections(
    context: ArtifactPublishContext,
    *,
    source_diagnostics: ArtifactSectionPublisher,
    evidence: ArtifactSectionPublisher,
    quality: ArtifactSectionPublisher,
    agentic: ArtifactSectionPublisher,
    report: ArtifactSectionPublisher,
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for publisher in (source_diagnostics, evidence, quality, agentic, report):
        refs.extend(publisher(context))
    return refs


__all__ = ["ArtifactSectionPublisher", "publish_daily_artifact_sections"]
