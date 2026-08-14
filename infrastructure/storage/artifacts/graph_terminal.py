from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.agent.artifacts.stores.errors import (
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.agent.artifacts.stores.fs_safety import reject_link_chain
from framework.harness.artifacts import (
    GraphTerminalManifest,
    parse_graph_terminal_manifest,
)


DEFAULT_MAX_GRAPH_TERMINAL_MANIFEST_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_GRAPH_ARTIFACT_READ_BYTES = 64 * 1024 * 1024


class FilesystemGraphTerminalArtifactReader:
    """Read-only adapter for canonical Graph terminal manifests and content."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_manifest_bytes: int = DEFAULT_MAX_GRAPH_TERMINAL_MANIFEST_BYTES,
        max_artifact_bytes: int = DEFAULT_MAX_GRAPH_ARTIFACT_READ_BYTES,
    ) -> None:
        self.root = Path(root)
        self.max_manifest_bytes = _positive_int(max_manifest_bytes, "max_manifest_bytes")
        self.max_artifact_bytes = _positive_int(max_artifact_bytes, "max_artifact_bytes")

    def read_terminal_manifest(self, run_id: str) -> GraphTerminalManifest:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        path = self._path(validated_run_id, "manifest.json")
        content = self._read_regular_file(
            path,
            identity=f"{validated_run_id}/manifest.json",
            max_bytes=self.max_manifest_bytes,
            missing_role="Graph terminal manifest",
        )
        try:
            payload = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid Graph terminal manifest JSON: {validated_run_id}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ArtifactStoreMetadataError(
                f"invalid Graph terminal manifest shape: {validated_run_id}"
            )
        return parse_graph_terminal_manifest(
            payload,
            expected_run_id=validated_run_id,
        )

    def read_artifact_content(self, *, run_id: str, relative_path: str) -> bytes:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        validated_path = validate_relative_artifact_path(
            relative_path,
            field="artifact path",
        )
        path = self._path(validated_run_id, validated_path)
        return self._read_regular_file(
            path,
            identity=f"{validated_run_id}/{validated_path}",
            max_bytes=self.max_artifact_bytes,
            missing_role="Graph artifact",
        )

    def _path(self, run_id: str, relative_path: str) -> Path:
        root = self.root.resolve(strict=False)
        validated_path = validate_relative_artifact_path(
            relative_path,
            field="artifact path",
        )
        relative_parts = (run_id, *PurePosixPath(validated_path).parts)
        resolve_artifact_descendant(
            root,
            *relative_parts,
            field="artifact path",
        )
        return root.joinpath(*relative_parts)

    def _read_regular_file(
        self,
        path: Path,
        *,
        identity: str,
        max_bytes: int,
        missing_role: str,
    ) -> bytes:
        root = self.root.resolve(strict=False)
        try:
            reject_link_chain(path, root=root, identity=identity, role=missing_role)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"{missing_role} not found: {identity}"
            ) from exc
        try:
            before = os.lstat(path)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"{missing_role} not found: {identity}") from exc
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactStoreMetadataError(
                f"{missing_role} is not a regular file: {identity}"
            )
        if before.st_size > max_bytes:
            raise ArtifactStoreMetadataError(
                f"{missing_role} exceeds configured read limit: {identity}"
            )
        try:
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
                    before,
                    opened,
                ):
                    raise ArtifactStoreMetadataError(
                        f"{missing_role} identity changed while opening: {identity}"
                    )
                reject_link_chain(
                    path,
                    root=root,
                    identity=identity,
                    role=missing_role,
                )
                content = handle.read(max_bytes + 1)
        except (IsADirectoryError, OSError) as exc:
            raise ArtifactStoreMetadataError(
                f"{missing_role} could not be read: {identity}"
            ) from exc
        if len(content) > max_bytes:
            raise ArtifactStoreMetadataError(
                f"{missing_role} exceeds configured read limit: {identity}"
            )
        return content


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


__all__ = [
    "DEFAULT_MAX_GRAPH_ARTIFACT_READ_BYTES",
    "DEFAULT_MAX_GRAPH_TERMINAL_MANIFEST_BYTES",
    "FilesystemGraphTerminalArtifactReader",
]
