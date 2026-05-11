from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from storage.artifacts.models import ArtifactRef, ArtifactWriteRequest


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class ArtifactNotFoundError(FileNotFoundError):
    pass


class ArtifactChecksumMismatchError(ValueError):
    pass


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

        checksum = sha256(data).hexdigest()
        return ArtifactRef(
            artifact_id=artifact_id,
            run_id=artifact.run_id,
            step_id=artifact.step_id,
            artifact_type=artifact.artifact_type,
            path=_normalize_relative_path(relative_path),
            content_type=artifact.content_type,
            size_bytes=len(data),
            checksum=checksum,
            redacted=artifact.redacted,
            created_at=artifact.created_at,
            metadata=dict(artifact.metadata),
        )

    def read(self, artifact_ref: ArtifactRef) -> bytes:
        path = self._artifact_path(artifact_ref.run_id, artifact_ref.path)
        if not path.exists():
            raise ArtifactNotFoundError(f"artifact not found: {artifact_ref.run_id}/{artifact_ref.path}")
        data = path.read_bytes()
        if artifact_ref.checksum and sha256(data).hexdigest() != artifact_ref.checksum:
            raise ArtifactChecksumMismatchError(f"artifact checksum mismatch: {artifact_ref.artifact_id}")
        return data

    def exists(self, artifact_ref: ArtifactRef) -> bool:
        return self._artifact_path(artifact_ref.run_id, artifact_ref.path).exists()

    def delete(self, artifact_ref: ArtifactRef) -> None:
        path = self._artifact_path(artifact_ref.run_id, artifact_ref.path)
        if path.exists():
            path.unlink()

    def _artifact_path(self, run_id: str, relative_path: str) -> Path:
        _validate_id(run_id, "run_id")
        relative = _validate_relative_path(relative_path)
        return self.root / run_id / relative


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
    return _validate_relative_path(value).as_posix()


def _validate_relative_path(value: str) -> Path:
    if not value:
        raise ValueError("artifact path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid artifact path: {value}")
    return relative


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")
