from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.agent.artifacts.models import ArtifactManifest
from framework.agent.artifacts.stores import ArtifactStore


@dataclass(frozen=True)
class ArtifactReplayBundle:
    manifest: ArtifactManifest
    contents: dict[str, bytes] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "artifact_count": len(self.contents),
            "content_keys": sorted(self.contents),
        }


class ArtifactReplayBundleBuilder:
    def __init__(self, store: ArtifactStore | None = None) -> None:
        self.store = store

    def build(self, manifest: ArtifactManifest, store: ArtifactStore | None = None) -> ArtifactReplayBundle:
        actual_store = store or self.store
        contents: dict[str, bytes] = {}
        if actual_store is not None:
            for ref in manifest.artifacts:
                artifact = actual_store.get(ref.artifact_id)
                if artifact is not None:
                    contents[ref.artifact_id] = artifact.content_bytes()
        return ArtifactReplayBundle(manifest=manifest, contents=contents)
