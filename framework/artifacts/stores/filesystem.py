from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath
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
    ArtifactStoreMetadataError,
)
from framework.artifacts.stores.fs_safety import (
    reject_link_chain,
    verified_atomic_write,
)
from framework.artifacts.stores.integrity import verify_sha256_checksum


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
        target = self._raw_artifact_path(artifact.run_id, relative_path)
        data = artifact.content_bytes()
        verified_atomic_write(
            target,
            data,
            root=self.root,
            identity=f"{artifact.run_id}/{artifact_id}",
        )

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
        path = self._raw_artifact_path(artifact_ref.run_id, artifact_ref.path)
        try:
            data = _read_verified_regular_file(
                path,
                root=self.root.resolve(strict=False),
                artifact_id=artifact_ref.artifact_id,
            )
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {artifact_ref.run_id}/{artifact_ref.path}") from exc
        except (IsADirectoryError, OSError) as exc:
            raise ArtifactStoreMetadataError(
                f"artifact is not a regular file: {artifact_ref.artifact_id}"
            ) from exc
        if artifact_ref.checksum:
            verify_sha256_checksum(
                data,
                artifact_ref.checksum,
                artifact_id=artifact_ref.artifact_id,
                store="filesystem",
                operation="read",
            )
        if artifact_ref.size_bytes is not None and len(data) != artifact_ref.size_bytes:
            raise ArtifactStoreMetadataError(
                f"artifact size mismatch: {artifact_ref.artifact_id}"
            )
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
        path = self._raw_artifact_path(artifact_ref.run_id, artifact_ref.path)
        try:
            content = _read_verified_regular_file(
                path,
                root=self.root.resolve(strict=False),
                artifact_id=artifact_ref.artifact_id,
            )
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {artifact_ref.run_id}/{artifact_ref.path}") from exc
        except (IsADirectoryError, OSError) as exc:
            raise ArtifactStoreMetadataError(
                f"artifact is not a regular file: {artifact_ref.artifact_id}"
            ) from exc
        return compute_checksum(content)

    def delete(self, artifact_ref: ArtifactRef) -> None:
        path = self._artifact_path(artifact_ref.run_id, artifact_ref.path)
        if path.exists():
            path.unlink()

    def _artifact_path(self, run_id: str, relative_path: str) -> Path:
        validate_artifact_path_segment(run_id, field="run_id")
        relative = validate_relative_artifact_path(relative_path, field="artifact path")
        run_dir = resolve_artifact_descendant(self.root, run_id, field="run_id")
        return resolve_artifact_descendant(run_dir, relative, field="artifact path")

    def _raw_artifact_path(self, run_id: str, relative_path: str) -> Path:
        """Return a lexical path so reads can reject final symlinks before open."""

        validate_artifact_path_segment(run_id, field="run_id")
        relative = validate_relative_artifact_path(relative_path, field="artifact path")
        root = self.root.resolve(strict=False)
        path = root.joinpath(run_id, *PurePosixPath(relative).parts)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ArtifactStoreMetadataError("artifact path escapes the artifact root") from exc
        return path


def _read_verified_regular_file(path: Path, *, root: Path, artifact_id: str) -> bytes:
    _reject_symlink_chain(path, root=root, artifact_id=artifact_id)
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise ArtifactStoreMetadataError(
            f"artifact is not a regular file: {artifact_id}"
        )
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ArtifactStoreMetadataError(
                    f"artifact is not a regular file: {artifact_id}"
                )
            if not os.path.samestat(before, opened):
                raise ArtifactStoreMetadataError(
                    f"artifact identity changed while opening: {artifact_id}"
                )
            _reject_symlink_chain(path, root=root, artifact_id=artifact_id)
            return handle.read()
    except FileNotFoundError:
        raise
    except IsADirectoryError:
        raise


def _reject_symlink_chain(path: Path, *, root: Path, artifact_id: str) -> None:
    reject_link_chain(
        path,
        root=root,
        identity=artifact_id,
        role="artifact",
    )


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


__all__ = [
    "ArtifactChecksumMismatchError",
    "ArtifactNotFoundError",
    "FilesystemArtifactStore",
]
