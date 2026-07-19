from __future__ import annotations

import contextvars
import json
import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactReference,
    ArtifactManager,
    ArtifactRef as StorageArtifactRef,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
    FilesystemArtifactStore,
    compute_checksum,
    validate_artifact_path_segment,
)
from framework.artifacts.stores.integrity import validate_sha256_checksum
from framework.harness import (
    ArtifactRef as HarnessArtifactRef,
    ArtifactWriteRequest,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps
from framework.shared.time import format_datetime, utc_now
from infrastructure.research.diagnostics import emit_research_persistence_diagnostic


CANONICAL_ARTIFACT_SCHEME = "artifact"
CANONICAL_ARTIFACT_DIRECTORY = "artifacts"


class ArtifactRunBindingError(HarnessValidationError):
    """Raised when a Research artifact operation has no safe run binding."""


class ArtifactWriteConflictError(ArtifactStoreMetadataError):
    """Raised when an immutable canonical artifact would be overwritten."""


class FilesystemHarnessArtifactPort:
    """Persist Harness JSON artifacts below one context-local Research run."""

    def __init__(
        self,
        root: str | Path = ".newsroom/runs",
        *,
        artifact_manager: ArtifactManager | None = None,
        artifact_store: FilesystemArtifactStore | None = None,
        max_write_bytes: int | None = None,
    ) -> None:
        if max_write_bytes is not None and max_write_bytes < 0:
            raise ValueError("max_write_bytes must be non-negative")
        configured_root = Path(root)
        if artifact_manager is not None:
            manager_root = Path(artifact_manager.root)
            if manager_root.resolve(strict=False) != configured_root.resolve(strict=False):
                raise ValueError("artifact_manager root does not match root")
        self.root = configured_root
        self.manager = artifact_manager or ArtifactManager(
            self.root,
            max_write_bytes=max_write_bytes,
        )
        self.store = artifact_store or FilesystemArtifactStore(self.root)
        self.max_write_bytes = (
            max_write_bytes
            if max_write_bytes is not None
            else self.manager.max_write_bytes
        )
        self._manifest_lock = threading.RLock()
        self._run_binding: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            f"filesystem_harness_artifact_run_{id(self)}",
            default=None,
        )

    @property
    def current_run_id(self) -> str | None:
        return self._run_binding.get()

    @contextmanager
    def bind_run(self, run_id: str) -> Iterator[str]:
        validated = validate_artifact_path_segment(run_id, field="run_id")
        token = self._run_binding.set(validated)
        try:
            yield validated
        finally:
            self._run_binding.reset(token)

    def write_artifact(self, request: ArtifactWriteRequest) -> HarnessArtifactRef:
        run_id = self.current_run_id
        try:
            result = self._write_artifact(request)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="artifact_store",
                operation="artifact_write",
                outcome="failed",
                reason=_artifact_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="artifact_store",
            operation="artifact_write",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
        )
        return result

    def _write_artifact(self, request: ArtifactWriteRequest) -> HarnessArtifactRef:
        run_id = self._require_bound_run()
        if not isinstance(request, ArtifactWriteRequest):
            raise TypeError("request must be ArtifactWriteRequest")
        artifact_type = validate_artifact_path_segment(
            request.artifact_type,
            field="artifact_type",
        )
        request_run_id = request.metadata.get("run_id")
        if request_run_id is not None and request_run_id != run_id:
            raise ArtifactRunBindingError(
                "artifact metadata run_id conflicts with the bound run"
            )
        canonical_payload = request.to_dict()
        _assert_finite_json(canonical_payload)
        try:
            content = stable_json_dumps(canonical_payload).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreMetadataError(
                f"artifact payload is not JSON serializable: {artifact_type}"
            ) from exc
        self._enforce_size(content, artifact_type)

        relative_path = self._canonical_path(artifact_type)
        checksum = compute_checksum(content)
        with self._manifest_lock:
            self._ensure_run_manifest(run_id)
            existing = self._existing_artifact_result(
                run_id=run_id,
                artifact_type=artifact_type,
                request=request,
                content=content,
                checksum=checksum,
            )
            if existing is not None:
                return existing
            self.manager.write_bytes(run_id, relative_path, content)
            self.manager.append_manifest_artifact(
                run_id,
                artifact_key=artifact_type,
                relative_path=relative_path,
                artifact_ref=ArtifactReference(
                    artifact_id=artifact_type,
                    run_id=run_id,
                    kind=artifact_type,
                    uri=relative_path,
                    content_type=request.media_type,
                    checksum=checksum,
                    size_bytes=len(content),
                    metadata=dict(request.metadata),
                ),
            )
        return HarnessArtifactRef(
            ref=self._canonical_ref(run_id, artifact_type),
            artifact_type=artifact_type,
            checksum=f"sha256:{checksum}",
            media_type=request.media_type,
            metadata=dict(request.metadata),
        )

    def read_artifact(self, ref: str) -> dict[str, Any]:
        run_id: str | None = None
        try:
            run_id, artifact_type = self._parse_ref(ref)
            result = self._read_artifact(run_id, artifact_type)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="artifact_store",
                operation="artifact_read",
                outcome="failed",
                reason=_artifact_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="artifact_store",
            operation="artifact_read",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
        )
        return result

    def _read_artifact(self, run_id: str, artifact_type: str) -> dict[str, Any]:
        manifest = self.manager.read_run_manifest(run_id)
        if not isinstance(manifest.get("manifest_hash"), str):
            raise ArtifactStoreMetadataError(
                f"artifact manifest hash is missing: {run_id}"
            )
        relative_path = self._canonical_path(artifact_type)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or artifacts.get(artifact_type) != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest path mismatch: {artifact_type}"
            )

        metadata = self._manifest_metadata(manifest, artifact_type, run_id, relative_path)
        checksum = validate_sha256_checksum(
            metadata["checksum"],
            artifact_id=artifact_type,
            field="artifact manifest checksum",
        )
        size_bytes = metadata["size_bytes"]
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise ArtifactStoreMetadataError(
                f"invalid artifact manifest size: {artifact_type}"
            )
        content_type = metadata["content_type"]
        if not isinstance(content_type, str) or not content_type.strip():
            raise ArtifactStoreMetadataError(
                f"invalid artifact manifest content_type: {artifact_type}"
            )
        self._enforce_size(size_bytes, artifact_type)
        content = self.store.read(
            StorageArtifactRef(
                artifact_id=artifact_type,
                run_id=run_id,
                artifact_type=artifact_type,
                path=relative_path,
                content_type=content_type,
                size_bytes=size_bytes,
                checksum=checksum,
            )
        )
        try:
            payload = json.loads(
                content.decode("utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid artifact JSON: {artifact_type}"
            ) from exc
        if not isinstance(payload, dict):
            raise ArtifactStoreMetadataError(
                f"invalid artifact JSON shape: {artifact_type}"
            )
        if payload.get("artifact_type") != artifact_type:
            raise ArtifactStoreMetadataError(
                f"artifact type mismatch: {artifact_type}"
            )
        payload_metadata = payload.get("metadata")
        if not isinstance(payload_metadata, dict):
            raise ArtifactStoreMetadataError(
                f"artifact metadata shape is invalid: {artifact_type}"
            )
        payload_run_id = payload_metadata.get("run_id")
        if payload_run_id is not None and payload_run_id != run_id:
            raise ArtifactStoreMetadataError(
                f"artifact payload run identity mismatch: {artifact_type}"
            )
        return payload

    def _existing_artifact_result(
        self,
        *,
        run_id: str,
        artifact_type: str,
        request: ArtifactWriteRequest,
        content: bytes,
        checksum: str,
    ) -> HarnessArtifactRef | None:
        manifest = self.manager.read_run_manifest(run_id)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or artifact_type not in artifacts:
            return None
        existing_path = artifacts.get(artifact_type)
        expected_path = self._canonical_path(artifact_type)
        if existing_path != expected_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest path mismatch: {artifact_type}"
            )
        metadata = self._manifest_metadata(
            manifest,
            artifact_type,
            run_id,
            expected_path,
        )
        existing_checksum = validate_sha256_checksum(
            metadata["checksum"],
            artifact_id=artifact_type,
            field="artifact manifest checksum",
        )
        existing_size = metadata.get("size_bytes")
        existing_content_type = metadata.get("content_type")
        if (
            existing_checksum != checksum
            or existing_size != len(content)
            or existing_content_type != request.media_type
        ):
            raise ArtifactWriteConflictError(
                f"immutable artifact already exists with different content: {artifact_type}"
            )
        existing_payload = self._read_artifact(run_id, artifact_type)
        if stable_json_dumps(existing_payload) != stable_json_dumps(request.to_dict()):
            raise ArtifactWriteConflictError(
                f"immutable artifact metadata conflicts: {artifact_type}"
            )
        return HarnessArtifactRef(
            ref=self._canonical_ref(run_id, artifact_type),
            artifact_type=artifact_type,
            checksum=f"sha256:{existing_checksum}",
            media_type=str(existing_content_type),
            metadata=dict(request.metadata),
        )

    def _require_bound_run(self) -> str:
        run_id = self._run_binding.get()
        if run_id is None:
            raise ArtifactRunBindingError("artifact write requires a bound run")
        return run_id

    def _ensure_run_manifest(self, run_id: str) -> None:
        try:
            self.manager.read_run_manifest(run_id)
            return
        except ArtifactNotFoundError:
            pass
        started_at = format_datetime(utc_now()) or ""
        self.manager.create_run_manifest(
            run_id=run_id,
            workflow_id="research.paper_analysis",
            workflow_version="1",
            profile="research",
            status="running",
            started_at=started_at,
            run_type="research",
        )

    def _manifest_metadata(
        self,
        manifest: dict[str, Any],
        artifact_type: str,
        run_id: str,
        relative_path: str,
    ) -> dict[str, Any]:
        all_metadata = manifest.get("artifact_metadata")
        if not isinstance(all_metadata, dict):
            raise ArtifactStoreMetadataError(
                f"artifact manifest metadata is missing: {artifact_type}"
            )
        metadata = all_metadata.get(artifact_type)
        if not isinstance(metadata, dict):
            raise ArtifactStoreMetadataError(
                f"artifact manifest metadata is missing: {artifact_type}"
            )
        if metadata.get("artifact_id") != artifact_type:
            raise ArtifactStoreMetadataError(
                f"artifact manifest artifact identity mismatch: {artifact_type}"
            )
        if metadata.get("run_id") != run_id:
            raise ArtifactStoreMetadataError(
                f"artifact manifest run identity mismatch: {artifact_type}"
            )
        if metadata.get("path") != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest path mismatch: {artifact_type}"
            )

        refs = manifest.get("artifact_refs")
        ref = _find_manifest_entry(refs, artifact_type)
        if ref is None:
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref is missing: {artifact_type}"
            )
        if (ref.get("uri") or ref.get("path")) != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref path mismatch: {artifact_type}"
            )
        if (ref.get("content_hash") or ref.get("checksum")) != metadata.get("checksum"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref checksum mismatch: {artifact_type}"
            )
        if ref.get("size_bytes") != metadata.get("size_bytes"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref size mismatch: {artifact_type}"
            )

        index = manifest.get("artifact_index")
        indexed = _find_manifest_entry(index, artifact_type)
        if indexed is None:
            raise ArtifactStoreMetadataError(
                f"artifact manifest index is missing: {artifact_type}"
            )
        if indexed.get("run_id") != run_id or indexed.get("path") != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest index identity mismatch: {artifact_type}"
            )
        if indexed.get("checksum") != metadata.get("checksum"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest index checksum mismatch: {artifact_type}"
            )
        if indexed.get("size_bytes") != metadata.get("size_bytes"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest index size mismatch: {artifact_type}"
            )
        return metadata

    def _enforce_size(self, content_or_size: bytes | int, artifact_type: str) -> None:
        if self.max_write_bytes is None:
            return
        size = len(content_or_size) if isinstance(content_or_size, bytes) else content_or_size
        if size > self.max_write_bytes:
            raise ValueError(
                f"artifact exceeds max_write_bytes: {artifact_type} ({size} > {self.max_write_bytes})"
            )

    @staticmethod
    def _canonical_path(artifact_type: str) -> str:
        return f"{CANONICAL_ARTIFACT_DIRECTORY}/{artifact_type}.json"

    @staticmethod
    def _canonical_ref(run_id: str, artifact_type: str) -> str:
        return f"{CANONICAL_ARTIFACT_SCHEME}://{run_id}/{artifact_type}"

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str]:
        if not isinstance(ref, str) or not ref:
            raise ArtifactStoreMetadataError("artifact ref is required")
        try:
            parsed = urlsplit(ref)
        except ValueError as exc:
            raise ArtifactStoreMetadataError("artifact ref is invalid") from exc
        if parsed.scheme != CANONICAL_ARTIFACT_SCHEME or parsed.query or parsed.fragment:
            raise ArtifactStoreMetadataError("artifact ref is not canonical")
        if not parsed.netloc or ":" in parsed.netloc or parsed.path.count("/") != 1:
            raise ArtifactStoreMetadataError("artifact ref is not canonical")
        run_id = validate_artifact_path_segment(parsed.netloc, field="artifact ref run_id")
        artifact_type = validate_artifact_path_segment(
            parsed.path.lstrip("/"),
            field="artifact ref artifact_type",
        )
        canonical = FilesystemHarnessArtifactPort._canonical_ref(run_id, artifact_type)
        if ref != canonical:
            raise ArtifactStoreMetadataError("artifact ref is not canonical")
        return run_id, artifact_type


def _find_manifest_entry(entries: Any, artifact_id: str) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for item in entries:
        if isinstance(item, dict) and item.get("artifact_id") == artifact_id:
            return item
    return None


def _assert_finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ArtifactStoreMetadataError("artifact JSON contains non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_json(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_finite_json(item)


def _reject_nonfinite_json(value: str) -> Any:
    raise ArtifactStoreMetadataError(
        f"artifact JSON contains non-finite number: {value}"
    )


def _artifact_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ArtifactRunBindingError):
        return "run_binding_invalid"
    if isinstance(exc, ArtifactWriteConflictError):
        return "write_conflict"
    if isinstance(exc, ArtifactChecksumMismatchError):
        return "checksum_invalid"
    if isinstance(exc, ArtifactStoreMetadataError):
        return "metadata_invalid"
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_input"
    if isinstance(exc, OSError):
        return "filesystem_unavailable"
    return "other"


__all__ = [
    "ArtifactRunBindingError",
    "ArtifactWriteConflictError",
    "CANONICAL_ARTIFACT_DIRECTORY",
    "CANONICAL_ARTIFACT_SCHEME",
    "FilesystemHarnessArtifactPort",
]
