from __future__ import annotations

from framework.artifacts.models import Artifact, ArtifactReference
from framework.artifacts.stores import ArtifactStore


class ArtifactResolver:
    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def resolve(self, ref: ArtifactReference) -> Artifact:
        artifact = self.store.get(ref.artifact_id)
        if artifact is None:
            raise FileNotFoundError(f"artifact not found: {ref.artifact_id}")
        return artifact

    def exists(self, ref: ArtifactReference) -> bool:
        return self.store.get(ref.artifact_id) is not None
