from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Self
from urllib.parse import urlsplit

from framework.agent.artifacts import ArtifactManager, compute_checksum
from framework.agent.artifacts.paths import (
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.agent.artifacts.stores.fs_safety import (
    is_link_or_reparse_point,
    reject_link_chain,
    verified_atomic_write,
    verified_exclusive_file_lock,
)
from framework.agent.artifacts.stores.integrity import validate_sha256_checksum
from framework.events.canonical import checksum_for
from framework.harness.artifacts import (
    GraphArtifactDeletionReceipt,
    GraphArtifactPhysicalDeleteRequest,
    GraphArtifactQuarantineReceipt,
    GraphTerminalManifest,
)
from framework.harness.runtime.materializer import RESULT_PAYLOAD_SCHEMA
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    checksum,
    non_negative_int,
    reference,
    serialize_candidate,
    sha256_checksum,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    ArtifactRecord,
    ResultSensitivity,
    RetentionClass,
)
from framework.shared.hashing import hash_text
from framework.shared.json import stable_json_dumps
from framework.shared.time import utc_now
from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.storage.artifacts import FilesystemGraphTerminalArtifactStore


GRAPH_ARTIFACT_LIFECYCLE_SCHEMA_VERSION = "newsroom.graph-artifact-lifecycle/v1"
DEFAULT_MAX_GRAPH_ARTIFACT_PHYSICAL_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_GRAPH_ARTIFACT_LIFECYCLE_STATE_BYTES = 64 * 1024
_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "request_checksum",
        "ref",
        "physical_checksum",
        "physical_byte_size",
        "quarantine_receipt",
        "deletion_receipt",
        "state_checksum",
    }
)
_GRAPH_RESULT_PREFIX = "graph-result-"
_EXPECTED_WRAPPER_KEYS = frozenset(
    {"artifact_type", "payload", "media_type", "metadata"}
)
_EXPECTED_PAYLOAD_KEYS = frozenset(
    {
        "schema",
        "candidate_checksum",
        "candidate_bytes",
        "media_type",
        "encoding",
        "value",
    }
)
_EXPECTED_METADATA_KEYS = frozenset(
    {
        "tenant_id",
        "run_id",
        "graph_id",
        "node_id",
        "attempt_id",
        "candidate_checksum",
        "graph_result_ref_only",
        "identity_checksum",
        "required_for_replay",
        "required_for_publication",
    }
)


@dataclass(frozen=True, slots=True)
class _LifecycleState:
    operation_id: str
    request_checksum: str
    ref: str
    physical_checksum: str
    physical_byte_size: int
    quarantine_receipt: GraphArtifactQuarantineReceipt | None = None
    deletion_receipt: GraphArtifactDeletionReceipt | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_id",
            reference(self.operation_id, "lifecycle_state.operation_id"),
        )
        object.__setattr__(
            self,
            "request_checksum",
            checksum(self.request_checksum, "lifecycle_state.request_checksum"),
        )
        object.__setattr__(self, "ref", reference(self.ref, "lifecycle_state.ref"))
        object.__setattr__(
            self,
            "physical_checksum",
            checksum(self.physical_checksum, "lifecycle_state.physical_checksum"),
        )
        object.__setattr__(
            self,
            "physical_byte_size",
            non_negative_int(
                self.physical_byte_size,
                "lifecycle_state.physical_byte_size",
            ),
        )
        if self.quarantine_receipt is not None and (
            not isinstance(
                self.quarantine_receipt,
                GraphArtifactQuarantineReceipt,
            )
            or self.quarantine_receipt.operation_id != self.operation_id
            or self.quarantine_receipt.ref != self.ref
        ):
            raise _gc_error("lifecycle.state.quarantine")
        if self.deletion_receipt is not None and (
            not isinstance(self.deletion_receipt, GraphArtifactDeletionReceipt)
            or self.quarantine_receipt is None
            or self.deletion_receipt.operation_id != self.operation_id
            or self.deletion_receipt.ref != self.ref
            or self.deletion_receipt.quarantine_receipt_checksum
            != self.quarantine_receipt.receipt_checksum
        ):
            raise _gc_error("lifecycle.state.deletion")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_ARTIFACT_LIFECYCLE_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "request_checksum": self.request_checksum,
            "ref": self.ref,
            "physical_checksum": self.physical_checksum,
            "physical_byte_size": self.physical_byte_size,
            "quarantine_receipt": (
                self.quarantine_receipt.to_dict()
                if self.quarantine_receipt is not None
                else None
            ),
            "deletion_receipt": (
                self.deletion_receipt.to_dict()
                if self.deletion_receipt is not None
                else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        unsigned = self.unsigned_dict()
        return {**unsigned, "state_checksum": checksum_for(unsigned)}

    @classmethod
    def from_dict(cls, value: Any) -> Self:
        if not isinstance(value, Mapping) or set(value) != _STATE_FIELDS:
            raise _gc_error("lifecycle.state.schema")
        if value.get("schema_version") != GRAPH_ARTIFACT_LIFECYCLE_SCHEMA_VERSION:
            raise _gc_error("lifecycle.state.version")
        unsigned = {key: value[key] for key in _STATE_FIELDS if key != "state_checksum"}
        if checksum(value.get("state_checksum"), "lifecycle_state.state_checksum") != checksum_for(
            unsigned
        ):
            raise _gc_error("lifecycle.state.checksum")
        quarantine_value = value.get("quarantine_receipt")
        deletion_value = value.get("deletion_receipt")
        return cls(
            operation_id=value.get("operation_id"),
            request_checksum=value.get("request_checksum"),
            ref=value.get("ref"),
            physical_checksum=value.get("physical_checksum"),
            physical_byte_size=value.get("physical_byte_size"),
            quarantine_receipt=(
                GraphArtifactQuarantineReceipt.from_dict(quarantine_value)
                if quarantine_value is not None
                else None
            ),
            deletion_receipt=(
                GraphArtifactDeletionReceipt.from_dict(deletion_value)
                if deletion_value is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class _ManifestEvidence:
    physical_checksum: str
    physical_byte_size: int


@dataclass(frozen=True, slots=True)
class _Target:
    run_id: str
    artifact_type: str
    relative_path: str
    source_path: Path


class FilesystemGraphArtifactLifecycle:
    """Quarantine and purge only catalog-detached internal Graph results."""

    def __init__(
        self,
        root: str | Path = ".newsroom/runs",
        *,
        artifact_port: FilesystemHarnessArtifactPort | None = None,
        artifact_manager: ArtifactManager | None = None,
        terminal_store: FilesystemGraphTerminalArtifactStore | None = None,
        clock: Callable[[], datetime] = utc_now,
        max_physical_bytes: int = DEFAULT_MAX_GRAPH_ARTIFACT_PHYSICAL_BYTES,
        max_state_bytes: int = DEFAULT_MAX_GRAPH_ARTIFACT_LIFECYCLE_STATE_BYTES,
    ) -> None:
        configured_root = Path(root)
        if artifact_port is not None and (
            artifact_port.root.resolve(strict=False)
            != configured_root.resolve(strict=False)
        ):
            raise ValueError("artifact_port root does not match root")
        if artifact_manager is not None and (
            artifact_manager.root.resolve(strict=False)
            != configured_root.resolve(strict=False)
        ):
            raise ValueError("artifact_manager root does not match root")
        if terminal_store is not None and (
            terminal_store.root.resolve(strict=False)
            != configured_root.resolve(strict=False)
        ):
            raise ValueError("terminal_store root does not match root")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if (
            isinstance(max_physical_bytes, bool)
            or not isinstance(max_physical_bytes, int)
            or max_physical_bytes <= 0
        ):
            raise ValueError("max_physical_bytes must be a positive integer")
        if (
            isinstance(max_state_bytes, bool)
            or not isinstance(max_state_bytes, int)
            or max_state_bytes <= 0
        ):
            raise ValueError("max_state_bytes must be a positive integer")
        self.root = configured_root
        self.artifact_port = artifact_port or FilesystemHarnessArtifactPort(
            self.root,
            artifact_manager=artifact_manager,
            terminal_store=terminal_store,
        )
        self.manager = self.artifact_port.manager
        self.terminal_store = terminal_store or self.artifact_port.terminal_store
        if self.terminal_store is not self.artifact_port.terminal_store:
            raise ValueError("artifact_port and lifecycle must share terminal_store")
        self._clock = clock
        self.max_physical_bytes = max_physical_bytes
        self.max_state_bytes = max_state_bytes

    def quarantine(
        self,
        request: GraphArtifactPhysicalDeleteRequest,
    ) -> GraphArtifactQuarantineReceipt:
        if not isinstance(request, GraphArtifactPhysicalDeleteRequest):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="lifecycle.quarantine.request",
            )
        try:
            return self._quarantine(request)
        except GraphArtifactResultError:
            raise
        except Exception as exc:
            raise _gc_error("lifecycle.quarantine") from exc

    def purge(
        self,
        receipt: GraphArtifactQuarantineReceipt,
    ) -> GraphArtifactDeletionReceipt:
        if not isinstance(receipt, GraphArtifactQuarantineReceipt):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="lifecycle.purge.receipt",
            )
        try:
            return self._purge(receipt)
        except GraphArtifactResultError:
            raise
        except Exception as exc:
            raise _gc_error("lifecycle.purge") from exc

    def _quarantine(
        self,
        request: GraphArtifactPhysicalDeleteRequest,
    ) -> GraphArtifactQuarantineReceipt:
        target = self._validated_target(request.record)
        if (
            request.record.expires_at is None
            or request.record.expires_at > request.detach_receipt.detached_at
            or request.detach_receipt.detached_at > request.requested_at
        ):
            raise result_error(
                GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID,
                field="lifecycle.record.retention",
            )
        paths = self._operation_paths(request.operation_id)
        with verified_exclusive_file_lock(
            paths["lock"],
            root=self.root,
            identity=request.operation_id,
        ):
            with self.artifact_port.lock_run(target.run_id):
                state = self._load_state(paths["state"])
                manifest = self.terminal_store.read_terminal_manifest(target.run_id)
                evidence = self._manifest_evidence(
                    manifest,
                    record=request.record,
                    target=target,
                )
                if state is None:
                    if evidence is None:
                        raise _gc_error("lifecycle.manifest.detached_without_state")
                    content = self._read_and_verify_payload(
                        target.source_path,
                        record=request.record,
                        artifact_type=target.artifact_type,
                    )
                    self._verify_physical_evidence(content, evidence)
                    state = _LifecycleState(
                        operation_id=request.operation_id,
                        request_checksum=request.request_checksum,
                        ref=request.record.ref,
                        physical_checksum=f"sha256:{compute_checksum(content)}",
                        physical_byte_size=len(content),
                    )
                    self._write_state(paths["state"], state)
                else:
                    self._validate_state_request(state, request)

                if state.quarantine_receipt is not None:
                    if state.deletion_receipt is not None and self._regular_file_exists(
                        paths["payload"],
                        identity=request.operation_id,
                    ):
                        raise _gc_error("lifecycle.quarantine.bytes_reappeared")
                    self._verify_existing_quarantine(
                        paths["payload"],
                        state=state,
                        record=request.record,
                        artifact_type=target.artifact_type,
                        allow_missing=state.deletion_receipt is not None,
                    )
                    return state.quarantine_receipt

                if evidence is not None:
                    if (
                        evidence.physical_checksum != state.physical_checksum
                        or evidence.physical_byte_size != state.physical_byte_size
                    ):
                        raise _gc_error("lifecycle.manifest.physical_identity")
                    content = self._read_and_verify_payload(
                        target.source_path,
                        record=request.record,
                        artifact_type=target.artifact_type,
                    )
                    self._verify_state_content(content, state)
                    self._detach_manifest_member(
                        manifest,
                        run_id=target.run_id,
                        artifact_type=target.artifact_type,
                    )

                source_exists = self._regular_file_exists(
                    target.source_path,
                    identity=request.operation_id,
                )
                quarantine_exists = self._regular_file_exists(
                    paths["payload"],
                    identity=request.operation_id,
                )
                if source_exists and quarantine_exists:
                    raise _gc_error("lifecycle.quarantine.duplicate_bytes")
                if source_exists:
                    content = self._read_and_verify_payload(
                        target.source_path,
                        record=request.record,
                        artifact_type=target.artifact_type,
                    )
                    self._verify_state_content(content, state)
                    self._atomic_move(
                        target.source_path,
                        paths["payload"],
                        identity=request.operation_id,
                    )
                elif quarantine_exists:
                    self._verify_existing_quarantine(
                        paths["payload"],
                        state=state,
                        record=request.record,
                        artifact_type=target.artifact_type,
                    )
                else:
                    raise _gc_error("lifecycle.quarantine.bytes_missing")

                quarantined_at = max(
                    aware_datetime(self._clock(), "lifecycle.clock"),
                    request.requested_at,
                )
                receipt = GraphArtifactQuarantineReceipt.create(
                    operation_id=request.operation_id,
                    ref=request.record.ref,
                    content_checksum=request.record.content_checksum,
                    byte_size=request.record.byte_size,
                    quarantined_at=quarantined_at,
                )
                self._write_state(
                    paths["state"],
                    replace(state, quarantine_receipt=receipt),
                )
                return receipt

    def _purge(
        self,
        receipt: GraphArtifactQuarantineReceipt,
    ) -> GraphArtifactDeletionReceipt:
        paths = self._operation_paths(receipt.operation_id)
        with verified_exclusive_file_lock(
            paths["lock"],
            root=self.root,
            identity=receipt.operation_id,
        ):
            state = self._load_state(paths["state"])
            if state is None or state.quarantine_receipt != receipt:
                raise _gc_error("lifecycle.purge.receipt")
            if state.deletion_receipt is not None:
                if self._regular_file_exists(
                    paths["payload"],
                    identity=receipt.operation_id,
                ):
                    raise _gc_error("lifecycle.purge.bytes_reappeared")
                return state.deletion_receipt

            if self._regular_file_exists(
                paths["payload"],
                identity=receipt.operation_id,
            ):
                content = self._read_regular_file(
                    paths["payload"],
                    identity=receipt.operation_id,
                )
                self._verify_state_content(content, state)
                self._unlink_verified(
                    paths["payload"],
                    identity=receipt.operation_id,
                )

            deleted_at = max(
                aware_datetime(self._clock(), "lifecycle.clock"),
                receipt.quarantined_at,
            )
            deletion = GraphArtifactDeletionReceipt.create(
                operation_id=receipt.operation_id,
                quarantine_receipt_checksum=receipt.receipt_checksum,
                ref=receipt.ref,
                content_checksum=receipt.content_checksum,
                byte_size=receipt.byte_size,
                deleted_at=deleted_at,
            )
            self._write_state(
                paths["state"],
                replace(state, deletion_receipt=deletion),
            )
            return deletion

    def _validated_target(self, record: ArtifactRecord) -> _Target:
        if not isinstance(record, ArtifactRecord):
            raise _gc_error("lifecycle.record")
        try:
            parsed = urlsplit(record.ref)
        except ValueError as exc:
            raise _scope_error("lifecycle.ref") from exc
        if (
            parsed.scheme != "artifact"
            or not parsed.netloc
            or ":" in parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path.count("/") != 1
        ):
            raise _scope_error("lifecycle.ref")
        run_id = validate_artifact_path_segment(
            parsed.netloc,
            field="graph artifact lifecycle run_id",
        )
        artifact_type = validate_artifact_path_segment(
            parsed.path.lstrip("/"),
            field="graph artifact lifecycle artifact_type",
        )
        if record.ref != f"artifact://{run_id}/{artifact_type}":
            raise _scope_error("lifecycle.ref")
        if (
            run_id != record.run_id
            or artifact_type != record.artifact_type
            or not artifact_type.startswith(_GRAPH_RESULT_PREFIX)
        ):
            raise _scope_error("lifecycle.record.scope")
        identity_suffix = artifact_type.removeprefix(_GRAPH_RESULT_PREFIX)
        if len(identity_suffix) != 64:
            raise _scope_error("lifecycle.record.identity")
        try:
            int(identity_suffix, 16)
        except ValueError as exc:
            raise _scope_error("lifecycle.record.identity") from exc
        if (
            record.sensitivity is not ResultSensitivity.INTERNAL
            or record.required_for_publication
            or record.required_for_replay
            or record.artifact_class is ArtifactClass.REPORT
            or record.retention_class is RetentionClass.REPORT
        ):
            raise result_error(
                GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID,
                field="lifecycle.record.protection",
            )
        file_name = f"{artifact_type}.json"
        if len(file_name) > 80:
            file_name = f"a-{hash_text(artifact_type)}.json"
        relative_path = validate_relative_artifact_path(
            f"artifacts/{file_name}",
            field="graph artifact lifecycle path",
        )
        root = self.root.resolve(strict=False)
        source_path = root.joinpath(run_id, *PurePosixPath(relative_path).parts)
        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise _scope_error("lifecycle.path") from exc
        return _Target(
            run_id=run_id,
            artifact_type=artifact_type,
            relative_path=relative_path,
            source_path=source_path,
        )

    def _manifest_evidence(
        self,
        manifest: GraphTerminalManifest,
        *,
        record: ArtifactRecord,
        target: _Target,
    ) -> _ManifestEvidence | None:
        if not isinstance(manifest, GraphTerminalManifest):
            raise _gc_error("lifecycle.manifest.schema")
        artifact = manifest.artifact(target.artifact_type)
        if artifact is None:
            return None
        metadata = artifact.metadata
        if (
            artifact.artifact_id != target.artifact_type
            or artifact.ref != record.ref
            or artifact.relative_path != target.relative_path
            or artifact.media_type != "application/json"
            or artifact.node_id != record.node_id
            or artifact.attempt_id != record.attempt_id
            or artifact.required_for_replay != record.required_for_replay
            or artifact.required_for_publication != record.required_for_publication
        ):
            raise _gc_error("lifecycle.manifest.membership")
        expected_metadata = {
            "tenant_id": record.tenant_id,
            "run_id": record.run_id,
            "graph_id": record.graph_id,
            "node_id": record.node_id,
            "attempt_id": record.attempt_id,
            "candidate_checksum": record.content_checksum,
            "graph_result_ref_only": True,
            "identity_checksum": (
                f"sha256:{target.artifact_type.removeprefix(_GRAPH_RESULT_PREFIX)}"
            ),
            "required_for_replay": record.required_for_replay,
            "required_for_publication": record.required_for_publication,
        }
        if any(
            metadata.get(key) != expected_value
            for key, expected_value in expected_metadata.items()
        ):
            raise _gc_error("lifecycle.manifest.internal_metadata")
        physical_checksum = validate_sha256_checksum(
            artifact.content_checksum.removeprefix("sha256:"),
            artifact_id=target.artifact_type,
            field="graph artifact lifecycle manifest checksum",
        )
        physical_size = artifact.byte_size
        if (
            isinstance(physical_size, bool)
            or not isinstance(physical_size, int)
            or physical_size < 0
            or physical_size > self.max_physical_bytes
        ):
            raise _gc_error("lifecycle.manifest.physical_size")
        return _ManifestEvidence(
            physical_checksum=f"sha256:{physical_checksum}",
            physical_byte_size=physical_size,
        )

    def _detach_manifest_member(
        self,
        manifest: GraphTerminalManifest,
        *,
        run_id: str,
        artifact_type: str,
    ) -> None:
        if manifest.run_id != run_id or manifest.manifest_hash is None:
            raise _gc_error("lifecycle.manifest.identity")
        updated = manifest.without_artifact(artifact_type)
        committed = self.terminal_store.replace_terminal_manifest(
            updated,
            expected_manifest_hash=manifest.manifest_hash,
        )
        if committed.artifact(artifact_type) is not None:
            raise _gc_error("lifecycle.manifest.detach")

    def _read_and_verify_payload(
        self,
        path: Path,
        *,
        record: ArtifactRecord,
        artifact_type: str,
    ) -> bytes:
        content = self._read_regular_file(path, identity=record.ref)
        try:
            wrapper = json.loads(
                content.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant: {value}")
                ),
            )
            if (
                not isinstance(wrapper, Mapping)
                or set(wrapper) != _EXPECTED_WRAPPER_KEYS
            ):
                raise ValueError("wrapper schema")
            if (
                wrapper.get("artifact_type") != artifact_type
                or wrapper.get("media_type") != "application/json"
            ):
                raise ValueError("wrapper identity")
            metadata = wrapper.get("metadata")
            if (
                not isinstance(metadata, Mapping)
                or set(metadata) != _EXPECTED_METADATA_KEYS
            ):
                raise ValueError("metadata schema")
            expected_metadata = {
                "tenant_id": record.tenant_id,
                "run_id": record.run_id,
                "graph_id": record.graph_id,
                "node_id": record.node_id,
                "attempt_id": record.attempt_id,
                "candidate_checksum": record.content_checksum,
                "graph_result_ref_only": True,
                "identity_checksum": (
                    f"sha256:{artifact_type.removeprefix(_GRAPH_RESULT_PREFIX)}"
                ),
                "required_for_replay": record.required_for_replay,
                "required_for_publication": record.required_for_publication,
            }
            if dict(metadata) != expected_metadata:
                raise ValueError("metadata identity")
            payload = wrapper.get("payload")
            if (
                not isinstance(payload, Mapping)
                or set(payload) != _EXPECTED_PAYLOAD_KEYS
            ):
                raise ValueError("payload schema")
            if (
                payload.get("schema") != RESULT_PAYLOAD_SCHEMA
                or payload.get("candidate_checksum") != record.content_checksum
                or payload.get("candidate_bytes") != record.byte_size
                or payload.get("media_type") != record.media_type
            ):
                raise ValueError("payload identity")
            encoding = payload.get("encoding")
            if encoding == "json":
                candidate = payload.get("value")
            elif encoding == "text":
                candidate = payload.get("value")
            elif encoding == "base64":
                candidate = base64.b64decode(payload.get("value"), validate=True)
            else:
                raise ValueError("payload encoding")
            _, candidate_bytes = serialize_candidate(candidate, record.media_type)
            if (
                len(candidate_bytes) != record.byte_size
                or sha256_checksum(candidate_bytes) != record.content_checksum
            ):
                raise ValueError("payload checksum")
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise _gc_error("lifecycle.payload") from exc
        return content

    def _read_regular_file(
        self,
        path: Path,
        *,
        identity: str,
        max_bytes: int | None = None,
    ) -> bytes:
        limit = self.max_physical_bytes if max_bytes is None else max_bytes
        reject_link_chain(
            path,
            root=self.root,
            identity=identity,
            role="graph artifact lifecycle",
        )
        before = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or is_link_or_reparse_point(before)
            or before.st_size > limit
        ):
            raise _gc_error("lifecycle.file")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or not os.path.samestat(before, opened)
            ):
                raise _gc_error("lifecycle.file.identity")
            content = handle.read(limit + 1)
        if len(content) != before.st_size or len(content) > limit:
            raise _gc_error("lifecycle.file.size")
        return content

    def _verify_existing_quarantine(
        self,
        path: Path,
        *,
        state: _LifecycleState,
        record: ArtifactRecord,
        artifact_type: str,
        allow_missing: bool = False,
    ) -> None:
        if not self._regular_file_exists(path, identity=state.operation_id):
            if allow_missing:
                return
            raise _gc_error("lifecycle.quarantine.bytes_missing")
        content = self._read_and_verify_payload(
            path,
            record=record,
            artifact_type=artifact_type,
        )
        self._verify_state_content(content, state)

    @staticmethod
    def _verify_physical_evidence(
        content: bytes,
        evidence: _ManifestEvidence,
    ) -> None:
        if (
            len(content) != evidence.physical_byte_size
            or f"sha256:{compute_checksum(content)}" != evidence.physical_checksum
        ):
            raise _gc_error("lifecycle.manifest.physical_identity")

    @staticmethod
    def _verify_state_content(content: bytes, state: _LifecycleState) -> None:
        if (
            len(content) != state.physical_byte_size
            or f"sha256:{compute_checksum(content)}" != state.physical_checksum
        ):
            raise _gc_error("lifecycle.quarantine.physical_identity")

    @staticmethod
    def _validate_state_request(
        state: _LifecycleState,
        request: GraphArtifactPhysicalDeleteRequest,
    ) -> None:
        if (
            state.operation_id != request.operation_id
            or state.request_checksum != request.request_checksum
            or state.ref != request.record.ref
        ):
            raise _gc_error("lifecycle.state.request")
        if state.quarantine_receipt is not None and (
            state.quarantine_receipt.content_checksum
            != request.record.content_checksum
            or state.quarantine_receipt.byte_size != request.record.byte_size
        ):
            raise _gc_error("lifecycle.state.record")

    def _operation_paths(self, operation_id: str) -> dict[str, Path]:
        normalized = reference(operation_id, "lifecycle.operation_id")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        base = (
            self.root.resolve(strict=False)
            / "_records"
            / "graph_artifact_lifecycle"
        )
        operation_root = base / "operations" / digest
        return {
            "lock": base / "operation_locks" / f"{digest}.lock",
            "state": operation_root / "state.json",
            "payload": operation_root / "payload.quarantine",
        }

    def _load_state(self, path: Path) -> _LifecycleState | None:
        try:
            content = self._read_regular_file(
                path,
                identity="graph-artifact-lifecycle-state",
                max_bytes=self.max_state_bytes,
            )
        except FileNotFoundError:
            return None
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise _gc_error("lifecycle.state.json") from exc
        try:
            return _LifecycleState.from_dict(value)
        except GraphArtifactResultError as exc:
            if exc.error_code is GraphArtifactResultErrorCode.GC_OPERATION_FAILED:
                raise
            raise _gc_error("lifecycle.state.contract") from exc

    def _write_state(self, path: Path, state: _LifecycleState) -> None:
        encoded = (stable_json_dumps(state.to_dict()) + "\n").encode("utf-8")
        if len(encoded) > self.max_state_bytes:
            raise _gc_error("lifecycle.state.size")
        verified_atomic_write(
            path,
            encoded,
            root=self.root,
            identity=state.operation_id,
        )

    def _regular_file_exists(self, path: Path, *, identity: str) -> bool:
        reject_link_chain(
            path,
            root=self.root,
            identity=identity,
            role="graph artifact lifecycle",
        )
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(info.st_mode) or is_link_or_reparse_point(info):
            raise _gc_error("lifecycle.file")
        return True

    def _atomic_move(self, source: Path, target: Path, *, identity: str) -> None:
        reject_link_chain(
            source,
            root=self.root,
            identity=identity,
            role="graph artifact source",
        )
        reject_link_chain(
            target,
            root=self.root,
            identity=identity,
            role="graph artifact quarantine",
        )
        source_info = os.lstat(source)
        if not stat.S_ISREG(source_info.st_mode) or is_link_or_reparse_point(source_info):
            raise _gc_error("lifecycle.move.source")
        if target.exists():
            raise _gc_error("lifecycle.move.target")
        source_parent = os.lstat(source.parent)
        target_parent = os.lstat(target.parent)
        if source_parent.st_dev != target_parent.st_dev:
            raise _gc_error("lifecycle.move.volume")
        os.replace(source, target)
        committed = os.lstat(target)
        if (
            not stat.S_ISREG(committed.st_mode)
            or is_link_or_reparse_point(committed)
            or not os.path.samestat(source_info, committed)
            or source.exists()
        ):
            raise _gc_error("lifecycle.move.commit")
        self._fsync_directory(source.parent)
        if target.parent != source.parent:
            self._fsync_directory(target.parent)

    def _unlink_verified(self, path: Path, *, identity: str) -> None:
        reject_link_chain(
            path,
            root=self.root,
            identity=identity,
            role="graph artifact purge",
        )
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or is_link_or_reparse_point(before):
            raise _gc_error("lifecycle.purge.file")
        current = os.lstat(path)
        if not os.path.samestat(before, current):
            raise _gc_error("lifecycle.purge.identity")
        os.unlink(path)
        if path.exists():
            raise _gc_error("lifecycle.purge.commit")
        self._fsync_directory(path.parent)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)


def _scope_error(field: str) -> GraphArtifactResultError:
    return result_error(
        GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
        field=field,
    )


def _gc_error(field: str) -> GraphArtifactResultError:
    return result_error(
        GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
        field=field,
    )


__all__ = [
    "DEFAULT_MAX_GRAPH_ARTIFACT_LIFECYCLE_STATE_BYTES",
    "DEFAULT_MAX_GRAPH_ARTIFACT_PHYSICAL_BYTES",
    "GRAPH_ARTIFACT_LIFECYCLE_SCHEMA_VERSION",
    "FilesystemGraphArtifactLifecycle",
]
