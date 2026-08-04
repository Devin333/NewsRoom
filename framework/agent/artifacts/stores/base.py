from __future__ import annotations

from typing import Protocol

from framework.agent.artifacts.models import Artifact, ArtifactReference


class ArtifactStore(Protocol):
    def put(self, artifact: Artifact) -> ArtifactReference:
        ...

    def get(self, artifact_id: str) -> Artifact | None:
        ...

    def delete(self, artifact_id: str) -> None:
        ...

    def list(self, prefix: str | None = None) -> list[ArtifactReference]:
        ...
