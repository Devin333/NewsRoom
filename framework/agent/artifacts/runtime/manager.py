from __future__ import annotations

import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from framework.agent.artifacts.models import Artifact, ArtifactReference
from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.agent.artifacts.stores import ArtifactStore, LocalArtifactStore
from framework.agent.artifacts.stores.errors import (
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.agent.artifacts.stores.integrity import validate_sha256_checksum
from framework.agent.artifacts.stores.fs_safety import (
    reject_link_chain,
    verified_atomic_write,
)
from framework.governance import CompositeAndGate, GateCheckResult
from framework.shared.json import to_jsonable
from framework.workflow.runtime.manifest import (
    RUN_MANIFEST_SCHEMA_VERSION,
    append_manifest_artifact_index,
    manifest_hash,
    normalize_legacy_run_manifest,
    register_manifest_artifact,
    register_manifest_artifact_ref,
)


class ArtifactManager:
    def __init__(
        self,
        root: str | Path,
        *,
        store: ArtifactStore | None = None,
        gate_enabled: bool = True,
        max_write_bytes: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.store = store or LocalArtifactStore(self.root)
        self.gate_enabled = gate_enabled
        self.max_write_bytes = max_write_bytes

    def publish(self, artifact: Artifact) -> ArtifactReference:
        return self.store.put(artifact)

    def resolve(self, ref: ArtifactReference) -> Artifact:
        artifact = self.store.get(ref.artifact_id)
        if artifact is None:
            raise FileNotFoundError(f"artifact not found: {ref.artifact_id}")
        return artifact

    def list(self, run_id: str | None = None) -> list[ArtifactReference]:
        return self.store.list(prefix=run_id)

    def delete(self, artifact_id: str) -> None:
        self.store.delete(artifact_id)

    def start_run(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def run_dir(self, run_id: str) -> Path:
        validate_artifact_path_segment(run_id, field="run_id")
        return resolve_artifact_descendant(self.root, run_id, field="run_id")

    def create_run_manifest(
        self,
        *,
        run_id: str,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        profile: str = "default",
        status: str = "created",
        started_at: str | None = None,
        run_type: str = "workflow",
    ) -> dict[str, Any]:
        manifest = normalize_legacy_run_manifest(
            {
                "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
                "run_type": run_type,
                "run_id": run_id,
                "workflow_id": workflow_id or "",
                "workflow_version": workflow_version or "",
                "profile": profile,
                "status": status,
                "started_at": started_at or "",
                "finished_at": None,
                "completed_at": None,
                "path": [],
                "steps": {},
                "artifacts": {"manifest": "manifest.json"},
            }
        )
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def read_run_manifest(self, run_id: str) -> dict[str, Any]:
        path = self._raw_target(run_id, "manifest.json")
        try:
            content = _read_verified_manifest_file(
                path,
                root=self.root.resolve(strict=False),
                run_id=run_id,
            )
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"run manifest not found: {run_id}") from exc
        except (IsADirectoryError, OSError) as exc:
            raise ArtifactStoreMetadataError(
                f"run manifest is not a regular file: {run_id}"
            ) from exc
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid run manifest JSON: {run_id}"
            ) from exc
        if not isinstance(payload, dict):
            raise ArtifactStoreMetadataError(
                f"invalid run manifest shape: {run_id}"
            )
        if payload.get("run_id") != run_id:
            raise ArtifactStoreMetadataError(
                f"run manifest identity mismatch: {run_id}"
            )
        persisted_hash = payload.get("manifest_hash")
        if persisted_hash is not None:
            expected_hash = validate_sha256_checksum(
                persisted_hash,
                artifact_id=run_id,
                field="run manifest hash",
            )
            if manifest_hash(payload) != expected_hash:
                raise ArtifactStoreMetadataError(
                    f"run manifest hash mismatch: {run_id}"
                )
        return normalize_legacy_run_manifest(payload)

    def update_run_manifest(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        manifest = self.read_run_manifest(run_id)
        manifest.update(dict(updates))
        _validate_manifest_artifact_paths(manifest)
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def append_manifest_artifact(
        self,
        run_id: str,
        *,
        artifact_key: str,
        relative_path: str,
        artifact_ref: ArtifactReference | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self.read_run_manifest(run_id)
        register_manifest_artifact(manifest, artifact_key, relative_path)
        if artifact_ref is None:
            artifact_ref = ArtifactReference(
                artifact_id=artifact_key,
                run_id=run_id,
                kind=artifact_key,
                uri=relative_path,
            )
        payload = artifact_ref.to_dict() if isinstance(artifact_ref, ArtifactReference) else dict(artifact_ref)
        if payload.get("artifact_type") is None and payload.get("kind") is not None:
            payload["artifact_type"] = payload["kind"]
        _normalize_manifest_artifact_checksum(payload)
        _validate_manifest_artifact_ref(
            run_id=run_id,
            relative_path=relative_path,
            payload=payload,
        )
        artifact_id = payload.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            _remove_manifest_artifact_ref(manifest, artifact_id)
        register_manifest_artifact_ref(manifest, payload)
        append_manifest_artifact_index(manifest, payload)
        _register_manifest_artifact_metadata(
            manifest,
            artifact_key=artifact_key,
            relative_path=relative_path,
            payload=payload,
        )
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def finalize_run_manifest(self, run_id: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = self.read_run_manifest(run_id)
        if updates:
            manifest.update(dict(updates))
        _validate_manifest_artifact_paths(manifest)
        manifest["completed_at"] = manifest.get("completed_at") or manifest.get("finished_at")
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def write_json(self, run_id: str, name: str, data: Any) -> Path:
        content = (
            json.dumps(
                to_jsonable(data),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        return self.write_bytes(run_id, name, content)

    def write_text(self, run_id: str, name: str, text: str) -> Path:
        return self.write_bytes(run_id, name, text.encode("utf-8"))

    def write_bytes(self, run_id: str, name: str, data: bytes) -> Path:
        self._gate_write(run_id, name, data)
        target = self._raw_target(run_id, name)
        verified_atomic_write(
            target,
            data,
            root=self.root,
            identity=f"{run_id}/{name}",
        )
        return target

    def _raw_target(self, run_id: str, name: str) -> Path:
        validate_artifact_path_segment(run_id, field="run_id")
        relative = validate_relative_artifact_path(name, field="artifact name")
        root = self.root.resolve(strict=False)
        path = root.joinpath(run_id, *PurePosixPath(relative).parts)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ArtifactStoreMetadataError(
                "artifact path escapes the artifact root"
            ) from exc
        return path

    def _gate_write(self, run_id: str, name: str, data: bytes) -> None:
        validate_artifact_path_segment(run_id, field="run_id")
        validate_relative_artifact_path(name, field="artifact name")
        if not self.gate_enabled:
            return
        relative = Path(name)
        checks = [
            GateCheckResult(
                check_id="artifact.path",
                dimension="artifact",
                passed=not relative.is_absolute() and ".." not in relative.parts,
                reason=f"artifact path is not relative to run directory: {name}",
                metadata={"run_id": run_id, "name": name},
            )
        ]
        if self.max_write_bytes is not None:
            checks.append(
                GateCheckResult(
                    check_id="artifact.size",
                    dimension="resource",
                    passed=len(data) <= self.max_write_bytes,
                    reason=(
                        f"artifact write exceeds max_write_bytes: {len(data)} > {self.max_write_bytes}"
                    ),
                    metadata={"size_bytes": len(data), "max_write_bytes": self.max_write_bytes},
                )
            )
        if any(token in str(name).casefold() for token in ("secret", "token", "password")):
            checks.append(
                GateCheckResult(
                    check_id="artifact.sensitive_name",
                    dimension="safety",
                    passed=False,
                    severity="warning",
                    reason=f"artifact name looks sensitive: {name}",
                )
            )
        gate = CompositeAndGate(f"artifact:{run_id}:{name}:gate").evaluate(checks)
        if gate.decision == "block":
            raise ValueError(f"artifact gate blocked: {gate.reason}; gate_result={gate.to_dict()}")


def _validate_manifest_artifact_paths(manifest: dict[str, Any]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("manifest artifacts must be an object")
    for artifact_key, relative_path in artifacts.items():
        if not isinstance(relative_path, str):
            raise ValueError(
                f"manifest artifact path must be a string: {artifact_key}"
            )
        validate_relative_artifact_path(
            relative_path,
            field=f"manifest_artifact_path[{artifact_key}]",
        )


def _validate_manifest_artifact_ref(
    *,
    run_id: str,
    relative_path: str,
    payload: dict[str, Any],
) -> None:
    ref_run_id = payload.get("run_id")
    if ref_run_id is not None and ref_run_id != run_id:
        raise ArtifactStoreMetadataError(
            f"manifest artifact run identity mismatch: {payload.get('artifact_id')}"
        )
    ref_path = payload.get("path") or payload.get("uri")
    if ref_path is not None and ref_path != relative_path:
        raise ArtifactStoreMetadataError(
            f"manifest artifact path mismatch: {payload.get('artifact_id')}"
        )


def _normalize_manifest_artifact_checksum(payload: dict[str, Any]) -> None:
    raw = payload.get("checksum") or payload.get("content_hash")
    if raw is None:
        return
    if isinstance(raw, str) and raw.startswith("sha256:"):
        raw = raw.removeprefix("sha256:")
    checksum = validate_sha256_checksum(
        raw,
        artifact_id=str(payload.get("artifact_id") or "manifest-artifact"),
        field="manifest artifact checksum",
    )
    if "checksum" in payload:
        payload["checksum"] = checksum
    if "content_hash" in payload:
        payload["content_hash"] = checksum


def _remove_manifest_artifact_ref(
    manifest: dict[str, Any],
    artifact_id: str,
) -> None:
    for field_name in ("artifact_refs", "artifact_index"):
        entries = manifest.get(field_name)
        if not isinstance(entries, list):
            continue
        manifest[field_name] = [
            item
            for item in entries
            if not isinstance(item, dict) or item.get("artifact_id") != artifact_id
        ]


def _register_manifest_artifact_metadata(
    manifest: dict[str, Any],
    *,
    artifact_key: str,
    relative_path: str,
    payload: dict[str, Any],
) -> None:
    checksum = payload.get("checksum") or payload.get("content_hash")
    content_type = payload.get("content_type") or payload.get("media_type")
    size_bytes = payload.get("size_bytes")
    if checksum is None or content_type is None or size_bytes is None:
        return
    metadata = manifest.setdefault("artifact_metadata", {})
    if not isinstance(metadata, dict):
        raise ArtifactStoreMetadataError(
            "run manifest artifact_metadata must be an object"
        )
    metadata[artifact_key] = {
        "artifact_id": payload.get("artifact_id"),
        "run_id": payload.get("run_id") or manifest.get("run_id"),
        "kind": payload.get("kind") or payload.get("artifact_type"),
        "path": relative_path,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "checksum": checksum,
    }


def _read_verified_manifest_file(path: Path, *, root: Path, run_id: str) -> bytes:
    _reject_manifest_symlink_chain(path, root=root, run_id=run_id)
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise ArtifactStoreMetadataError(
            f"run manifest is not a regular file: {run_id}"
        )
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ArtifactStoreMetadataError(
                f"run manifest is not a regular file: {run_id}"
            )
        if not os.path.samestat(before, opened):
            raise ArtifactStoreMetadataError(
                f"run manifest identity changed while opening: {run_id}"
            )
        _reject_manifest_symlink_chain(path, root=root, run_id=run_id)
        return handle.read()


def _reject_manifest_symlink_chain(path: Path, *, root: Path, run_id: str) -> None:
    reject_link_chain(
        path,
        root=root,
        identity=run_id,
        role="run manifest",
    )
