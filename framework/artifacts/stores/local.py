from __future__ import annotations

import json
from pathlib import Path

from framework.artifacts.models import Artifact, ArtifactReference, compute_checksum
from framework.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)


class LocalArtifactStore:
    def __init__(self, root: str | Path = ".newsroom/artifacts") -> None:
        self.root = Path(root)

    def put(self, artifact: Artifact) -> ArtifactReference:
        path = self.path_for(artifact.artifact_id)
        relative_uri = path.relative_to(self.root.resolve(strict=False)).as_posix()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = artifact.content_bytes()
        path.write_bytes(data)
        metadata_path = self._metadata_path(artifact.artifact_id)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(
                {
                    **artifact.to_dict(include_content=False),
                    "uri": relative_uri,
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
            uri=relative_uri,
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
        metadata_root = resolve_artifact_descendant(
            self.root,
            ".metadata",
            field="artifact metadata root",
        )
        if not metadata_root.exists():
            return []
        refs = []
        for candidate in sorted(metadata_root.glob("*.json")):
            path = resolve_artifact_descendant(
                metadata_root,
                candidate.name,
                field="artifact metadata path",
            )
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
        return resolve_artifact_descendant(
            self.root,
            "objects",
            safe_id,
            field="artifact_id",
        )

    def _metadata_path(self, artifact_id: str) -> Path:
        safe_id = _safe_artifact_id(artifact_id)
        return resolve_artifact_descendant(
            self.root,
            ".metadata",
            f"{safe_id}.json",
            field="artifact_id",
        )


def _safe_artifact_id(value: str) -> str:
    return validate_artifact_path_segment(value, field="artifact_id")
