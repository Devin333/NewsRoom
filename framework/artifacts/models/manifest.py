from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.artifacts.models.reference import ArtifactReference
from framework.shared.json import to_jsonable


@dataclass
class ArtifactManifest:
    run_id: str
    artifacts: list[ArtifactReference] = field(default_factory=list)
    schema_version: str = "framework.artifacts.manifest.v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        self.artifacts = [
            ref if isinstance(ref, ArtifactReference) else ArtifactReference.from_dict(ref)
            for ref in self.artifacts
        ]
        self.metadata = dict(self.metadata)

    def add(self, ref: ArtifactReference) -> None:
        self.artifacts.append(ref)

    def get(self, artifact_id: str) -> ArtifactReference | None:
        for ref in self.artifacts:
            if ref.artifact_id == artifact_id:
                return ref
        return None

    def list(self) -> list[ArtifactReference]:
        return list(self.artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "artifacts": [ref.to_dict() for ref in self.artifacts],
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactManifest":
        return cls(
            run_id=str(payload["run_id"]),
            artifacts=[
                ArtifactReference.from_dict(item)
                for item in payload.get("artifacts", [])
                if isinstance(item, dict)
            ],
            schema_version=str(payload.get("schema_version") or "framework.artifacts.manifest.v1"),
            metadata=dict(payload.get("metadata") or {}),
        )
