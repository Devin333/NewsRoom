from __future__ import annotations

import json
from pathlib import Path

from framework.artifacts.models import Artifact, ArtifactReference, compute_checksum


class LocalArtifactStore:
    def __init__(self, root: str | Path = ".newsroom/artifacts") -> None:
        self.root = Path(root)

    def put(self, artifact: Artifact) -> ArtifactReference:
        path = self.path_for(artifact.artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = artifact.content_bytes()
        path.write_bytes(data)
        metadata_path = self._metadata_path(artifact.artifact_id)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(
                {
                    **artifact.to_dict(include_content=False),
                    "uri": path.relative_to(self.root).as_posix(),
                    "checksum": compute_checksum(data),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return ArtifactReference(
            artifact_id=artifact.artifact_id,
            uri=path.relative_to(self.root).as_posix(),
            content_type=artifact.content_type,
            checksum=compute_checksum(data),
            metadata=dict(artifact.metadata),
        )

    def get(self, artifact_id: str) -> Artifact | None:
        path = self.path_for(artifact_id)
        metadata_path = self._metadata_path(artifact_id)
        if not path.exists() or not metadata_path.exists():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return Artifact(
            artifact_id=artifact_id,
            name=str(metadata.get("name") or artifact_id),
            content_type=str(metadata.get("content_type") or "application/octet-stream"),
            content=path.read_bytes(),
            metadata=dict(metadata.get("metadata") or {}),
            created_at=metadata.get("created_at"),
        )

    def delete(self, artifact_id: str) -> None:
        for path in (self.path_for(artifact_id), self._metadata_path(artifact_id)):
            if path.exists():
                path.unlink()

    def list(self, prefix: str | None = None) -> list[ArtifactReference]:
        metadata_root = self.root / ".metadata"
        if not metadata_root.exists():
            return []
        refs = []
        for path in sorted(metadata_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            ref = ArtifactReference(
                artifact_id=str(payload["artifact_id"]),
                uri=str(payload["uri"]),
                content_type=payload.get("content_type"),
                checksum=payload.get("checksum"),
                metadata=dict(payload.get("metadata") or {}),
            )
            if prefix is None or ref.uri.startswith(prefix) or ref.artifact_id.startswith(prefix):
                refs.append(ref)
        return refs

    def path_for(self, artifact_id: str) -> Path:
        safe_id = _safe_artifact_id(artifact_id)
        return self.root / "objects" / safe_id

    def _metadata_path(self, artifact_id: str) -> Path:
        safe_id = _safe_artifact_id(artifact_id)
        return self.root / ".metadata" / f"{safe_id}.json"


def _safe_artifact_id(value: str) -> str:
    if not value:
        raise ValueError("artifact_id is required")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"invalid artifact_id: {value}")
    return str(value)
