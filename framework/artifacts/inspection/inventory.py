from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.artifacts.models import ArtifactReference
from framework.artifacts.stores import ArtifactStore


@dataclass(frozen=True)
class ArtifactInventory:
    artifacts: list[ArtifactReference] = field(default_factory=list)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "artifacts": [ref.to_dict() for ref in self.artifacts],
        }


class ArtifactInventoryBuilder:
    def build(self, store: ArtifactStore) -> ArtifactInventory:
        return ArtifactInventory(artifacts=store.list())
