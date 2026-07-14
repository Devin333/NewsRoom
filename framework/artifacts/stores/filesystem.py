from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from framework.artifacts.models import ArtifactRef, ArtifactWriteRequest, compute_checksum
from framework.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.artifacts.stores.errors import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
)


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class FilesystemArtifactStore:
    def __init__(self, root: str | Path = ".newsroom/runs") -> None:
        self.root = Path(root)

    def write(self, artifact: ArtifactWriteRequest) -> ArtifactRef:
        _validate_id(artifact.run_id, "run_id")
        artifact_id = artifact.artifact_id or uuid4().hex
        _validate_id(artifact_id, "artifact_id")
        if artifact.step_id is not None:
            _validate_id(artifact.step_id, "step_id")
        if not artifact.artifact_type:
            raise ValueError("artifact_type is required")

        relative_path = artifact.relative_path or _default_relative_path(
            artifact_id=artifact_id,
            artifact_type=artifact.artifact_type,
            content_type=artifact.content_type,
            step_id=artifact.step_id,
        )
        target = self._artifact_path(artifact.run_id, relative_path)
        data = artifact.content_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        return ArtifactRef(
            artifact_id=artifact_id,
            run_id=artifact.run_id,
            step_id=artifact.step_id,
            artifact_type=artifact.artifact_type,
            path=_normalize_relative_path(relative_path),
            content_type=artifact.content_type,
            size_bytes=len(data),
            checksum=compute_checksum(data),
            redacted=artifact.redacted,
            created_at=artifact.created_at,
            metadata=dict(artifact.metadata),
        )

    def read(self, artifact_ref: ArtifactRef) -> bytes:
        path = self._artifact_path(artifact_ref.run_id, artifact_ref.path)
        if not path.exists():
            raise ArtifactNotFoundError(f"artifact not found: {artifact_ref.run_id}/{artifact_ref.path}")
        data = path.read_bytes()
        if artifact_ref.checksum and compute_checksum(data) != artifact_ref.checksum:
            raise ArtifactChecksumMismatchError(f"artifact checksum mismatch: {artifact_ref.artifact_id}")
        return data

    def exists(self, artifact_ref: ArtifactRef) -> bool:
        return self._artifact_path(artifact_ref.run_id, artifact_ref.path).exists()

    def list(self, run_id: str) -> list[str]:
        validate_artifact_path_segment(run_id, field="run_id")
        run_dir = resolve_artifact_descendant(self.root, run_id, field="run_id")
        if not run_dir.exists():
            return []
        paths: list[str] = []
        for candidate in run_dir.rglob("*"):
            relative_path = candidate.relative_to(run_dir).as_posix()
            path = resolve_artifact_descendant(
                run_dir,
                relative_path,
                field="artifact list path",
            )
            if path.is_file():
                paths.append(relative_path)
        return sorted(paths)

    def checksum(self, artifact_ref: ArtifactRef) -> str:
        path = self._artifact_path(artifact_ref.run_id, artifact_ref.path)
        if not path.exists():
            raise ArtifactNotFoundError(f"artifact not found: {artifact_ref.run_id}/{artifact_ref.path}")
        return compute_checksum(path.read_bytes())

    def delete(self, artifact_ref: ArtifactRef) -> None:
        path = self._artifact_path(artifact_ref.run_id, artifact_ref.path)
        if path.exists():
            path.unlink()

    def _artifact_path(self, run_id: str, relative_path: str) -> Path:
        validate_artifact_path_segment(run_id, field="run_id")
        relative = validate_relative_artifact_path(relative_path, field="artifact path")
        run_dir = resolve_artifact_descendant(self.root, run_id, field="run_id")
        return resolve_artifact_descendant(run_dir, relative, field="artifact path")


def _default_relative_path(
    *,
    artifact_id: str,
    artifact_type: str,
    content_type: str,
    step_id: str | None,
) -> str:
    extension = _extension_for_content_type(content_type)
    if step_id:
        return f"steps/{step_id}/artifacts/{artifact_id}{extension}"
    return f"artifacts/{_path_segment(artifact_type)}/{artifact_id}{extension}"


def _extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "application/json": ".json",
        "application/x-ndjson": ".jsonl",
        "text/markdown": ".md",
        "text/plain": ".txt",
    }.get(normalized, ".bin")


def _path_segment(value: str) -> str:
    segment = _SAFE_SEGMENT_RE.sub("_", value.strip())
    return segment.strip("._") or "artifact"


def _normalize_relative_path(value: str) -> str:
    return validate_relative_artifact_path(value, field="artifact path")


def _validate_id(value: str, label: str) -> None:
    validate_artifact_path_segment(value, field=label)
