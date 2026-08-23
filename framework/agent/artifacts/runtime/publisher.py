from __future__ import annotations

from typing import Protocol

from framework.agent.artifacts.models import Artifact, ArtifactReference
from framework.agent.artifacts.stores import ArtifactStore


class ArtifactPublisher(Protocol):
    publisher_id: str

    def publish(self, artifact: Artifact) -> ArtifactReference:
        ...


class DefaultArtifactPublisher:
    publisher_id = "default"

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def publish(self, artifact: Artifact) -> ArtifactReference:
        return self.store.put(artifact)


__all__ = [
    "ArtifactPublisher",
    "DefaultArtifactPublisher",
]
