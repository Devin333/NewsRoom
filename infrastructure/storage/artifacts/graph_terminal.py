from __future__ import annotations

import json
import os
import stat
import threading
from collections.abc import Mapping
from contextlib import contextmanager
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
from framework.agent.artifacts.stores.fs_safety import (
    reject_link_chain,
    verified_atomic_write,
    verified_exclusive_file_lock,
)
from framework.events.canonical import checksum_for
from framework.harness.artifacts import (
    GraphTerminalArtifact,
    GraphTerminalManifest,
    parse_graph_terminal_manifest,
)
from framework.shared.hashing import hash_text
from framework.shared.json import stable_json_dumps


DEFAULT_MAX_GRAPH_TERMINAL_MANIFEST_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_GRAPH_ARTIFACT_READ_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_GRAPH_STAGED_ARTIFACTS = 10_000
GRAPH_ARTIFACT_STAGING_SCHEMA = "newsroom.graph-artifact-staging/v1"


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


class FilesystemGraphTerminalArtifactStore(FilesystemGraphTerminalArtifactReader):
    """Atomic Graph terminal authority plus non-authoritative staging metadata."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_manifest_bytes: int = DEFAULT_MAX_GRAPH_TERMINAL_MANIFEST_BYTES,
        max_artifact_bytes: int = DEFAULT_MAX_GRAPH_ARTIFACT_READ_BYTES,
        max_staged_artifacts: int = DEFAULT_MAX_GRAPH_STAGED_ARTIFACTS,
    ) -> None:
        super().__init__(
            root,
            max_manifest_bytes=max_manifest_bytes,
            max_artifact_bytes=max_artifact_bytes,
        )
        self.max_staged_artifacts = _positive_int(
            max_staged_artifacts,
            "max_staged_artifacts",
        )
        self._thread_lock = threading.RLock()

    def write_terminal_manifest(
        self,
        manifest: GraphTerminalManifest,
    ) -> GraphTerminalManifest:
        if not isinstance(manifest, GraphTerminalManifest):
            raise TypeError("manifest must be GraphTerminalManifest")
        with self._locked_run(manifest.run_id):
            try:
                existing = self.read_terminal_manifest(manifest.run_id)
            except ArtifactNotFoundError:
                existing = None
            if existing is not None:
                if existing != manifest:
                    raise ArtifactStoreMetadataError(
                        f"Graph terminal manifest already exists with different content: {manifest.run_id}"
                    )
                return existing
            self._write_manifest_unlocked(manifest)
            return self.read_terminal_manifest(manifest.run_id)

    def replace_terminal_manifest(
        self,
        manifest: GraphTerminalManifest,
        *,
        expected_manifest_hash: str,
    ) -> GraphTerminalManifest:
        if not isinstance(manifest, GraphTerminalManifest):
            raise TypeError("manifest must be GraphTerminalManifest")
        if not isinstance(expected_manifest_hash, str) or not expected_manifest_hash:
            raise ValueError("expected_manifest_hash is required")
        with self._locked_run(manifest.run_id):
            existing = self.read_terminal_manifest(manifest.run_id)
            if existing.manifest_hash != expected_manifest_hash:
                raise ArtifactStoreMetadataError(
                    f"Graph terminal manifest changed before replacement: {manifest.run_id}"
                )
            if existing == manifest:
                return existing
            self._write_manifest_unlocked(manifest)
            return self.read_terminal_manifest(manifest.run_id)

    def stage_artifact(
        self,
        *,
        run_id: str,
        artifact: GraphTerminalArtifact,
    ) -> GraphTerminalArtifact:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        if not isinstance(artifact, GraphTerminalArtifact):
            raise TypeError("artifact must be GraphTerminalArtifact")
        expected_ref_prefix = f"artifact://{validated_run_id}/"
        if not artifact.ref.startswith(expected_ref_prefix):
            raise ArtifactStoreMetadataError(
                f"staged Graph artifact run identity mismatch: {artifact.artifact_key}"
            )
        with self._locked_run(validated_run_id):
            try:
                terminal = self.read_terminal_manifest(validated_run_id)
            except ArtifactNotFoundError:
                terminal = None
            if terminal is not None:
                existing_terminal = terminal.artifact(artifact.artifact_key)
                if existing_terminal == artifact:
                    return artifact
                raise ArtifactStoreMetadataError(
                    f"Graph terminal manifest is already committed: {validated_run_id}"
                )
            path = self._staging_record_path(
                validated_run_id,
                artifact.artifact_key,
            )
            if path.exists():
                existing = self._read_staging_record(path, validated_run_id)
                if existing != artifact:
                    raise ArtifactStoreMetadataError(
                        f"staged Graph artifact conflicts: {artifact.artifact_key}"
                    )
                return existing
            staged = self.list_staged_artifacts(validated_run_id)
            if len(staged) >= self.max_staged_artifacts:
                raise ArtifactStoreMetadataError(
                    f"Graph artifact staging limit exceeded: {validated_run_id}"
                )
            payload = {
                "schema_version": GRAPH_ARTIFACT_STAGING_SCHEMA,
                "run_id": validated_run_id,
                "artifact": artifact.to_dict(),
            }
            record = {**payload, "record_checksum": checksum_for(payload)}
            verified_atomic_write(
                path,
                (stable_json_dumps(record) + "\n").encode("utf-8"),
                root=self.root,
                identity=f"graph-artifact-staging:{validated_run_id}:{artifact.artifact_key}",
            )
            return self._read_staging_record(path, validated_run_id)

    def read_staged_artifact(
        self,
        *,
        run_id: str,
        artifact_key: str,
    ) -> GraphTerminalArtifact:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        validate_artifact_path_segment(artifact_key, field="artifact_key")
        path = self._staging_record_path(validated_run_id, artifact_key)
        try:
            return self._read_staging_record(path, validated_run_id)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"staged Graph artifact not found: {validated_run_id}/{artifact_key}"
            ) from exc

    def list_staged_artifacts(
        self,
        run_id: str,
    ) -> tuple[GraphTerminalArtifact, ...]:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        run_dir = self._staging_run_dir(validated_run_id)
        if not run_dir.exists():
            return ()
        reject_link_chain(
            run_dir,
            root=self.root.resolve(strict=False),
            identity=f"graph-artifact-staging:{validated_run_id}",
            role="Graph artifact staging directory",
        )
        candidates = tuple(sorted(run_dir.glob("*.json")))
        if len(candidates) > self.max_staged_artifacts:
            raise ArtifactStoreMetadataError(
                f"Graph artifact staging limit exceeded: {validated_run_id}"
            )
        artifacts = tuple(
            self._read_staging_record(path, validated_run_id)
            for path in candidates
        )
        keys = tuple(item.artifact_key for item in artifacts)
        if len(keys) != len(set(keys)):
            raise ArtifactStoreMetadataError(
                f"duplicate staged Graph artifact identity: {validated_run_id}"
            )
        return tuple(sorted(artifacts, key=lambda item: item.artifact_key))

    def _write_manifest_unlocked(self, manifest: GraphTerminalManifest) -> None:
        path = self._path(manifest.run_id, "manifest.json")
        verified_atomic_write(
            path,
            (stable_json_dumps(manifest.to_dict()) + "\n").encode("utf-8"),
            root=self.root,
            identity=f"graph-terminal-manifest:{manifest.run_id}",
        )

    def _read_staging_record(
        self,
        path: Path,
        expected_run_id: str,
    ) -> GraphTerminalArtifact:
        content = self._read_regular_file(
            path,
            identity=f"graph-artifact-staging:{expected_run_id}:{path.name}",
            max_bytes=self.max_manifest_bytes,
            missing_role="Graph artifact staging record",
        )
        try:
            value = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid Graph artifact staging record: {expected_run_id}"
            ) from exc
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "run_id",
            "artifact",
            "record_checksum",
        }:
            raise ArtifactStoreMetadataError(
                f"invalid Graph artifact staging schema: {expected_run_id}"
            )
        if (
            value.get("schema_version") != GRAPH_ARTIFACT_STAGING_SCHEMA
            or value.get("run_id") != expected_run_id
        ):
            raise ArtifactStoreMetadataError(
                f"Graph artifact staging identity mismatch: {expected_run_id}"
            )
        payload = {
            "schema_version": value["schema_version"],
            "run_id": value["run_id"],
            "artifact": value["artifact"],
        }
        if value.get("record_checksum") != checksum_for(payload):
            raise ArtifactStoreMetadataError(
                f"Graph artifact staging checksum mismatch: {expected_run_id}"
            )
        raw_artifact = value["artifact"]
        if not isinstance(raw_artifact, Mapping):
            raise ArtifactStoreMetadataError(
                f"invalid Graph artifact staging payload: {expected_run_id}"
            )
        try:
            artifact = GraphTerminalArtifact.from_dict(raw_artifact)
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid staged Graph artifact: {expected_run_id}"
            ) from exc
        if path != self._staging_record_path(
            expected_run_id,
            artifact.artifact_key,
        ):
            raise ArtifactStoreMetadataError(
                f"Graph artifact staging path mismatch: {expected_run_id}"
            )
        return artifact

    def _staging_run_dir(self, run_id: str) -> Path:
        return resolve_artifact_descendant(
            self.root,
            "_records",
            "gas",
            f"r-{hash_text(run_id)[:32]}",
            field="Graph artifact staging directory",
        )

    def _staging_record_path(self, run_id: str, artifact_key: str) -> Path:
        validate_artifact_path_segment(artifact_key, field="artifact_key")
        return resolve_artifact_descendant(
            self._staging_run_dir(run_id),
            f"a-{hash_text(artifact_key)[:32]}.json",
            field="Graph artifact staging record",
        )

    @contextmanager
    def _locked_run(self, run_id: str):
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        lock_path = resolve_artifact_descendant(
            self.root,
            "_records",
            "graph_terminal_manifest",
            "locks",
            f"run-{hash_text(validated_run_id)}.lock",
            field="Graph terminal manifest lock",
        )
        with self._thread_lock:
            with verified_exclusive_file_lock(
                lock_path,
                root=self.root.resolve(strict=False),
                identity=f"graph-terminal-manifest:{validated_run_id}",
            ):
                yield


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
    "DEFAULT_MAX_GRAPH_STAGED_ARTIFACTS",
    "DEFAULT_MAX_GRAPH_TERMINAL_MANIFEST_BYTES",
    "GRAPH_ARTIFACT_STAGING_SCHEMA",
    "FilesystemGraphTerminalArtifactReader",
    "FilesystemGraphTerminalArtifactStore",
]
