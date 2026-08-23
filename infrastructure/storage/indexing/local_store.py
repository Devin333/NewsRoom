from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, Self, runtime_checkable

from framework.agent.artifacts.stores.errors import ArtifactStoreMetadataError
from framework.agent.artifacts.stores.fs_safety import (
    is_link_or_reparse_point,
    reject_link_chain,
    verified_atomic_write,
    verified_exclusive_file_lock,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.indexing.contracts import (
    GraphArtifactIndexRecord,
    GraphEventIndexRecord,
    GraphStorageIndexCandidate,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexIdentity,
)


GRAPH_STORAGE_INDEX_SNAPSHOT_SCHEMA = "newsroom.graph-storage-index-snapshot/v1"
DEFAULT_MAX_GRAPH_INDEX_SNAPSHOT_BYTES = 256 * 1024 * 1024


class GraphStorageIndexWriteStatus(StrEnum):
    WRITTEN = "written"
    IDEMPOTENT = "idempotent"


@dataclass(frozen=True, slots=True)
class GraphStorageIndexSnapshot:
    """The immutable live index body for one exact Graph terminal identity."""

    candidate: GraphStorageIndexCandidate
    schema_version: str = GRAPH_STORAGE_INDEX_SNAPSHOT_SCHEMA
    snapshot_ref: str = field(init=False)
    snapshot_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, GraphStorageIndexCandidate):
            raise TypeError("candidate must be GraphStorageIndexCandidate")
        _validate_candidate(self.candidate)
        if self.schema_version != GRAPH_STORAGE_INDEX_SNAPSHOT_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index snapshot schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "snapshot_ref",
            _checksum_for(
                {
                    "schema_version": self.schema_version,
                    "identity_ref": self.identity.identity_ref,
                }
            ),
        )
        object.__setattr__(
            self,
            "snapshot_checksum",
            _checksum_for(self.checksum_projection()),
        )

    @property
    def identity(self) -> GraphStorageIndexIdentity:
        return self.candidate.identity

    @property
    def artifact_records(self):
        return self.candidate.artifact_records

    @property
    def event_records(self):
        return self.candidate.event_records

    @property
    def event_high_watermark(self) -> int:
        return self.candidate.event_high_watermark

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate": self.candidate.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "snapshot_ref": self.snapshot_ref,
            "snapshot_checksum": self.snapshot_checksum,
        }

    def verify_integrity(self) -> None:
        expected_ref = _checksum_for(
            {
                "schema_version": self.schema_version,
                "identity_ref": self.identity.identity_ref,
            }
        )
        if self.snapshot_ref != expected_ref:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index snapshot reference is invalid",
                field="snapshot_ref",
            )
        if self.snapshot_checksum != _checksum_for(self.checksum_projection()):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index snapshot checksum is invalid",
                field="snapshot_checksum",
            )
        try:
            self.candidate.verify_integrity()
        except (GraphStorageIndexError, TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index snapshot candidate is invalid",
                field="candidate",
            ) from exc

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "candidate",
                "snapshot_ref",
                "snapshot_checksum",
            },
            "Graph storage index snapshot",
        )
        try:
            candidate = GraphStorageIndexCandidate.from_dict(payload["candidate"])
            snapshot = cls(candidate=candidate, schema_version=payload["schema_version"])
        except (GraphStorageIndexError, TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index snapshot contract is invalid",
                field="snapshot",
            ) from exc
        if payload["snapshot_ref"] != snapshot.snapshot_ref:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_SCOPE_MISMATCH,
                "Graph storage index snapshot reference is invalid",
                field="snapshot_ref",
            )
        if payload["snapshot_checksum"] != snapshot.snapshot_checksum:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index snapshot checksum is invalid",
                field="snapshot_checksum",
            )
        return snapshot


@dataclass(frozen=True, slots=True)
class GraphStorageIndexWriteReceipt:
    identity_ref: str
    snapshot_ref: str
    snapshot_checksum: str
    storage_ref: str
    status: GraphStorageIndexWriteStatus | str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity_ref",
            _checksum(self.identity_ref, "identity_ref"),
        )
        object.__setattr__(
            self,
            "snapshot_ref",
            _checksum(self.snapshot_ref, "snapshot_ref"),
        )
        object.__setattr__(
            self,
            "snapshot_checksum",
            _checksum(self.snapshot_checksum, "snapshot_checksum"),
        )
        object.__setattr__(
            self,
            "storage_ref",
            _required_text(self.storage_ref, "storage_ref"),
        )
        object.__setattr__(self, "status", GraphStorageIndexWriteStatus(self.status))


@runtime_checkable
class GraphStorageIndexStorePort(Protocol):
    def write(
        self,
        candidate: GraphStorageIndexCandidate,
    ) -> GraphStorageIndexWriteReceipt: ...

    def read(
        self,
        identity: GraphStorageIndexIdentity,
    ) -> GraphStorageIndexSnapshot: ...

    def list_artifacts(
        self,
        identity: GraphStorageIndexIdentity,
        *,
        node_instance_id: str | None = None,
    ) -> tuple[Any, ...]: ...

    def list_events(
        self,
        identity: GraphStorageIndexIdentity,
        *,
        node_instance_id: str | None = None,
    ) -> tuple[Any, ...]: ...


class LocalGraphStorageIndexStore:
    """Durable live Graph index store with no pointer or fallback mode."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_snapshot_bytes: int = DEFAULT_MAX_GRAPH_INDEX_SNAPSHOT_BYTES,
    ) -> None:
        self.root = Path(root)
        if (
            isinstance(max_snapshot_bytes, bool)
            or not isinstance(max_snapshot_bytes, int)
            or max_snapshot_bytes < 1
        ):
            raise ValueError("max_snapshot_bytes must be a positive integer")
        self.max_snapshot_bytes = max_snapshot_bytes

    def write(
        self,
        candidate: GraphStorageIndexCandidate,
    ) -> GraphStorageIndexWriteReceipt:
        if not isinstance(candidate, GraphStorageIndexCandidate):
            raise TypeError("candidate must be GraphStorageIndexCandidate")
        try:
            candidate.verify_integrity()
            snapshot = GraphStorageIndexSnapshot(candidate=candidate)
        except (GraphStorageIndexError, TypeError, ValueError) as exc:
            if isinstance(exc, GraphStorageIndexError):
                raise
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index candidate is invalid",
                field="candidate",
            ) from exc
        target = self._snapshot_path(snapshot.identity)
        content = stable_json_dumps(snapshot.to_dict()).encode("utf-8") + b"\n"
        if len(content) > self.max_snapshot_bytes:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index snapshot exceeds the configured storage bound",
                field="snapshot",
            )
        identity = f"Graph storage index {snapshot.identity.identity_ref}"
        try:
            with verified_exclusive_file_lock(
                target.with_suffix(".lock"),
                root=self.root,
                identity=identity,
            ):
                try:
                    existing = self._read_path(target, identity=identity)
                except GraphStorageIndexError as exc:
                    if exc.code is not GraphStorageIndexErrorCode.INDEX_NOT_FOUND:
                        raise
                else:
                    if existing.snapshot_checksum != snapshot.snapshot_checksum:
                        raise GraphStorageIndexError(
                            GraphStorageIndexErrorCode.INDEX_CONFLICT,
                            "Graph storage index identity already has another body",
                            field="snapshot_checksum",
                        )
                    return self._receipt(
                        snapshot,
                        status=GraphStorageIndexWriteStatus.IDEMPOTENT,
                    )
                verified_atomic_write(
                    target,
                    content,
                    root=self.root,
                    identity=identity,
                )
        except ArtifactStoreMetadataError as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index path boundary rejected the target",
                field="snapshot_path",
            ) from exc
        return self._receipt(snapshot, status=GraphStorageIndexWriteStatus.WRITTEN)

    def read(
        self,
        identity: GraphStorageIndexIdentity,
    ) -> GraphStorageIndexSnapshot:
        if not isinstance(identity, GraphStorageIndexIdentity):
            raise TypeError("identity must be GraphStorageIndexIdentity")
        target = self._snapshot_path(identity)
        snapshot = self._read_path(
            target,
            identity=f"Graph storage index {identity.identity_ref}",
        )
        if snapshot.identity != identity:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_SCOPE_MISMATCH,
                "Graph storage index read-back changed the requested identity",
                field="identity",
            )
        return snapshot

    def list_artifacts(
        self,
        identity: GraphStorageIndexIdentity,
        *,
        node_instance_id: str | None = None,
    ) -> tuple[Any, ...]:
        snapshot = self.read(identity)
        if node_instance_id is None:
            return snapshot.artifact_records
        _required_text(node_instance_id, "node_instance_id")
        return tuple(
            record
            for record in snapshot.artifact_records
            if record.node_instance_id == node_instance_id
        )

    def list_events(
        self,
        identity: GraphStorageIndexIdentity,
        *,
        node_instance_id: str | None = None,
    ) -> tuple[Any, ...]:
        snapshot = self.read(identity)
        if node_instance_id is None:
            return snapshot.event_records
        _required_text(node_instance_id, "node_instance_id")
        return tuple(
            record
            for record in snapshot.event_records
            if record.node_instance_id == node_instance_id
        )

    def _snapshot_path(self, identity: GraphStorageIndexIdentity) -> Path:
        if not isinstance(identity, GraphStorageIndexIdentity):
            raise TypeError("identity must be GraphStorageIndexIdentity")
        digest = identity.identity_ref.removeprefix("sha256:")
        return self.root / f"index-{digest}.json"

    def _read_path(self, target: Path, *, identity: str) -> GraphStorageIndexSnapshot:
        canonical_root = self.root.resolve(strict=False)
        try:
            reject_link_chain(
                target,
                root=canonical_root,
                identity=identity,
                role="Graph storage index",
            )
            info = os.lstat(target)
        except FileNotFoundError as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_NOT_FOUND,
                "Graph storage index was not found",
                field="identity",
            ) from exc
        except ArtifactStoreMetadataError as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index path is unsafe",
                field="snapshot_path",
            ) from exc
        if not stat.S_ISREG(info.st_mode) or is_link_or_reparse_point(info):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index is not a regular file",
                field="snapshot_path",
            )
        if info.st_size > self.max_snapshot_bytes:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index exceeds the configured read bound",
                field="snapshot_path",
            )
        try:
            with target.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
                    info,
                    opened,
                ):
                    raise ArtifactStoreMetadataError(
                        f"Graph storage index identity changed while opening: {identity}"
                    )
                reject_link_chain(
                    target,
                    root=canonical_root,
                    identity=identity,
                    role="Graph storage index",
                )
                content = handle.read(self.max_snapshot_bytes + 1)
            if len(content) > self.max_snapshot_bytes:
                raise ArtifactStoreMetadataError(
                    f"Graph storage index exceeds the configured read bound: {identity}"
                )
            payload = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(payload, Mapping):
                raise TypeError("snapshot must be an object")
            return GraphStorageIndexSnapshot.from_dict(payload)
        except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, GraphStorageIndexError):
                raise
            if isinstance(exc, ArtifactStoreMetadataError):
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.INDEX_CORRUPT,
                    "Graph storage index read boundary rejected the file",
                    field="snapshot_path",
                ) from exc
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.INDEX_CORRUPT,
                "Graph storage index content is invalid",
                field="snapshot",
            ) from exc

    @staticmethod
    def _receipt(
        snapshot: GraphStorageIndexSnapshot,
        *,
        status: GraphStorageIndexWriteStatus,
    ) -> GraphStorageIndexWriteReceipt:
        digest = snapshot.identity.identity_ref.removeprefix("sha256:")
        return GraphStorageIndexWriteReceipt(
            identity_ref=snapshot.identity.identity_ref,
            snapshot_ref=snapshot.snapshot_ref,
            snapshot_checksum=snapshot.snapshot_checksum,
            storage_ref=f"graph-index://{digest}",
            status=status,
        )


def _checksum_for(value: Mapping[str, Any]) -> str:
    from framework.events.canonical import checksum_for

    return checksum_for(value)


def _validate_candidate(candidate: GraphStorageIndexCandidate) -> None:
    try:
        candidate.verify_integrity()
        rebuilt = GraphStorageIndexCandidate(
            identity=candidate.identity,
            artifact_records=tuple(
                GraphArtifactIndexRecord.from_dict(record.to_dict())
                for record in candidate.artifact_records
            ),
            event_records=tuple(
                GraphEventIndexRecord.from_dict(record.to_dict())
                for record in candidate.event_records
            ),
            schema_version=candidate.schema_version,
        )
    except (GraphStorageIndexError, TypeError, ValueError) as exc:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.INDEX_CORRUPT,
            "Graph storage index candidate is invalid",
            field="candidate",
        ) from exc
    if rebuilt != candidate:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.INDEX_CORRUPT,
            "Graph storage index candidate read-back changed its records",
            field="candidate",
        )


def _checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{field_name} must be a sha256 checksum")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a sha256 checksum")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty trimmed text")
    return value


def _exact_mapping(
    value: Any,
    expected: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} fields are invalid: unknown={sorted(actual - expected)}, "
            f"missing={sorted(expected - actual)}"
        )
    return dict(value)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


__all__ = [
    "DEFAULT_MAX_GRAPH_INDEX_SNAPSHOT_BYTES",
    "GRAPH_STORAGE_INDEX_SNAPSHOT_SCHEMA",
    "GraphStorageIndexSnapshot",
    "GraphStorageIndexStorePort",
    "GraphStorageIndexWriteReceipt",
    "GraphStorageIndexWriteStatus",
    "LocalGraphStorageIndexStore",
]
