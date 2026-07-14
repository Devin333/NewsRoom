from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from framework.artifacts.models import Artifact, ArtifactReference, compute_checksum
from framework.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.artifacts.stores.errors import (
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.artifacts.stores.integrity import (
    ARTIFACT_INTEGRITY_METADATA_KEY,
    CHECKSUM_MISSING_INTEGRITY,
    verify_sha256_checksum,
)
from framework.shared.time import parse_datetime


class LocalArtifactStore:
    def __init__(self, root: str | Path = ".newsroom/artifacts") -> None:
        self.root = Path(root)

    def put(self, artifact: Artifact) -> ArtifactReference:
        path = self.path_for(artifact.artifact_id)
        metadata_path = self._metadata_path(artifact.artifact_id)
        relative_uri = path.relative_to(self.root.resolve(strict=False)).as_posix()
        data = artifact.content_bytes()
        checksum = compute_checksum(data)
        metadata_bytes = (
            json.dumps(
                {
                    **artifact.to_dict(include_content=False),
                    "uri": relative_uri,
                    "checksum": checksum,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        object_temp: Path | None = None
        metadata_temp: Path | None = None
        try:
            object_temp = _write_owned_temp(path, data)
            metadata_temp = _write_owned_temp(metadata_path, metadata_bytes)
            os.replace(object_temp, path)
            os.replace(metadata_temp, metadata_path)
        finally:
            _remove_owned_temp(object_temp)
            _remove_owned_temp(metadata_temp)

        return ArtifactReference(
            artifact_id=artifact.artifact_id,
            uri=relative_uri,
            content_type=artifact.content_type,
            checksum=checksum,
            metadata=dict(artifact.metadata),
        )

    def get(self, artifact_id: str) -> Artifact | None:
        path = self.path_for(artifact_id)
        metadata_path = self._metadata_path(artifact_id)
        object_exists = path.exists()
        metadata_exists = metadata_path.exists()
        if not object_exists and not metadata_exists:
            return None
        if metadata_exists and not object_exists:
            raise ArtifactNotFoundError(f"artifact object not found: {artifact_id}")
        if object_exists and not metadata_exists:
            raise ArtifactStoreMetadataError(
                f"artifact metadata not found: {artifact_id}"
            )

        metadata = _load_metadata(metadata_path, artifact_id=artifact_id)
        expected_uri = path.relative_to(self.root.resolve(strict=False)).as_posix()
        parsed = _validate_metadata(
            metadata,
            artifact_id=artifact_id,
            expected_uri=expected_uri,
        )
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"artifact object not found: {artifact_id}"
            ) from exc
        checksum_missing = "checksum" not in metadata
        if not checksum_missing:
            verify_sha256_checksum(
                data,
                metadata["checksum"],
                artifact_id=artifact_id,
                field="artifact metadata checksum",
            )

        artifact_metadata = dict(parsed["metadata"])
        artifact_metadata.pop(ARTIFACT_INTEGRITY_METADATA_KEY, None)
        if checksum_missing:
            artifact_metadata[ARTIFACT_INTEGRITY_METADATA_KEY] = (
                CHECKSUM_MISSING_INTEGRITY
            )
        try:
            return Artifact(
                artifact_id=artifact_id,
                name=parsed["name"],
                content_type=parsed["content_type"],
                content=data,
                metadata=artifact_metadata,
                created_at=parsed["created_at"],
            )
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid artifact metadata for {artifact_id}"
            ) from exc

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


def _write_owned_temp(target: Path, content: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except BaseException:
        if descriptor != -1:
            os.close(descriptor)
        _remove_owned_temp(temp_path)
        raise


def _remove_owned_temp(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _load_metadata(path: Path, *, artifact_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata JSON: {artifact_id}"
        ) from exc
    if not isinstance(payload, dict):
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata shape: {artifact_id}"
        )
    return payload


def _validate_metadata(
    payload: dict[str, Any],
    *,
    artifact_id: str,
    expected_uri: str,
) -> dict[str, Any]:
    persisted_id = _required_metadata_string(payload, "artifact_id", artifact_id)
    if persisted_id != artifact_id:
        raise ArtifactStoreMetadataError(
            f"artifact metadata identity mismatch: {artifact_id}"
        )
    uri = _required_metadata_string(payload, "uri", artifact_id)
    if uri != expected_uri:
        raise ArtifactStoreMetadataError(
            f"artifact metadata URI mismatch: {artifact_id}"
        )
    name = _required_metadata_string(payload, "name", artifact_id)
    content_type = _required_metadata_string(payload, "content_type", artifact_id)
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata field metadata: {artifact_id}"
        )
    created_at = payload.get("created_at")
    try:
        parsed_created_at = parse_datetime(created_at)
    except (TypeError, ValueError) as exc:
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata field created_at: {artifact_id}"
        ) from exc
    if parsed_created_at is None:
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata field created_at: {artifact_id}"
        )
    return {
        "name": name,
        "content_type": content_type,
        "metadata": metadata,
        "created_at": parsed_created_at,
    }


def _required_metadata_string(
    payload: dict[str, Any],
    field: str,
    artifact_id: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata field {field}: {artifact_id}"
        )
    return value


__all__ = [
    "LocalArtifactStore",
]
