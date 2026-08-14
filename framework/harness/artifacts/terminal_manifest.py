from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Protocol, Self, runtime_checkable

from framework.events.canonical import (
    canonical_json_bytes,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


GRAPH_TERMINAL_MANIFEST_SCHEMA = "newsroom.graph-terminal-manifest/v1"
MAX_GRAPH_TERMINAL_ARTIFACTS = 10_000
MAX_GRAPH_TERMINAL_METADATA_BYTES = 64 * 1024
MAX_GRAPH_ARTIFACT_CONTENT_BYTES = 64 * 1024 * 1024

_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,511}\Z")
_REFERENCE = re.compile(
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s]{1,2040}\Z|"
    r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,2047}\Z"
)
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)
_WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"|?*')
_DOS_DEVICE_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
    re.IGNORECASE,
)
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_context",
        "raw_prompt",
        "refresh_token",
        "secret",
        "system_prompt",
        "token",
    }
)
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_credential",
    "_credentials",
    "_password",
    "_secret",
    "_token",
)
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})


class GraphTerminalStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HALTED = "halted"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class GraphTerminalManifestContext:
    """Pinned Graph identity required before terminal publication can commit."""

    tenant_id: str
    graph_id: str
    graph_version: str
    graph_schema_version: str
    compiler_version: str
    normalized_graph_checksum: str
    started_at: datetime
    terminal_node_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "graph_id"):
            object.__setattr__(
                self,
                field_name,
                _identifier(getattr(self, field_name), f"context.{field_name}"),
            )
        for field_name in (
            "graph_version",
            "graph_schema_version",
            "compiler_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _exact_version(getattr(self, field_name), f"context.{field_name}"),
            )
        object.__setattr__(
            self,
            "normalized_graph_checksum",
            _checksum(
                self.normalized_graph_checksum,
                "context.normalized_graph_checksum",
            ),
        )
        object.__setattr__(
            self,
            "started_at",
            _aware_datetime(self.started_at, "context.started_at"),
        )
        object.__setattr__(
            self,
            "terminal_node_ids",
            _stable_tuple(
                self.terminal_node_ids,
                "context.terminal_node_ids",
                normalize=_identifier,
                allow_empty=False,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "normalized_graph_checksum": self.normalized_graph_checksum,
            "started_at": format_datetime(self.started_at),
            "terminal_node_ids": list(self.terminal_node_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_keys(
            value,
            required=frozenset(
                {
                    "tenant_id",
                    "graph_id",
                    "graph_version",
                    "graph_schema_version",
                    "compiler_version",
                    "normalized_graph_checksum",
                    "started_at",
                    "terminal_node_ids",
                }
            ),
            model=cls.__name__,
        )
        payload["started_at"] = _datetime_from_json(
            payload["started_at"],
            "context.started_at",
        )
        return cls(**payload)


class GraphTerminalManifestErrorCode(StrEnum):
    SCHEMA_INVALID = "graph_terminal_manifest_schema_invalid"
    SCHEMA_UNSUPPORTED = "graph_terminal_manifest_schema_unsupported"
    HASH_MISMATCH = "graph_terminal_manifest_hash_mismatch"
    IDENTITY_MISMATCH = "graph_terminal_manifest_identity_mismatch"
    ARTIFACT_NOT_FOUND = "graph_terminal_manifest_artifact_not_found"
    ARTIFACT_CONTENT_TOO_LARGE = "graph_terminal_manifest_artifact_content_too_large"
    ARTIFACT_SIZE_MISMATCH = "graph_terminal_manifest_artifact_size_mismatch"
    ARTIFACT_CHECKSUM_MISMATCH = "graph_terminal_manifest_artifact_checksum_mismatch"
    ARTIFACT_CONTENT_INVALID = "graph_terminal_manifest_artifact_content_invalid"
    HISTORY_QUARANTINED = "graph_terminal_manifest_history_quarantined"


class GraphTerminalManifestError(ValueError):
    def __init__(
        self,
        code: GraphTerminalManifestErrorCode,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        self.code = GraphTerminalManifestErrorCode(code)
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GraphManifestHistoryDiagnostic:
    run_id: str
    observed_schema: str | None
    code: GraphTerminalManifestErrorCode = (
        GraphTerminalManifestErrorCode.HISTORY_QUARANTINED
    )
    disposition: str = "quarantine"
    owner: str = "offline-graph-history-migrator"
    resumable: bool = False
    executable: bool = False
    publishable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _identifier(self.run_id, "history.run_id"))
        observed = self.observed_schema
        if observed is not None:
            observed = _required_text(observed, "history.observed_schema", max_length=256)
        object.__setattr__(self, "observed_schema", observed)
        if self.disposition != "quarantine":
            raise _schema_error("history.disposition")
        if self.owner != "offline-graph-history-migrator":
            raise _schema_error("history.owner")
        if self.resumable or self.executable or self.publishable:
            raise _schema_error("history.authority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "run_id": self.run_id,
            "observed_schema": self.observed_schema,
            "disposition": self.disposition,
            "owner": self.owner,
            "resumable": self.resumable,
            "executable": self.executable,
            "publishable": self.publishable,
        }


class GraphTerminalManifestHistoryError(GraphTerminalManifestError):
    def __init__(self, diagnostic: GraphManifestHistoryDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(
            GraphTerminalManifestErrorCode.HISTORY_QUARANTINED,
            "legacy run manifest is quarantined for offline history migration",
            field="schema_version",
        )


@dataclass(frozen=True, slots=True)
class GraphTerminalPublicationEvidence:
    identity_scope_ref: str
    subject_scope_ref: str
    publication_authority_ref: str
    terminal_side_effect_outcome_ref: str
    artifact_evidence_ref: str
    artifact_member_evidence_ref: str
    committed_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "identity_scope_ref",
            "subject_scope_ref",
            "publication_authority_ref",
            "terminal_side_effect_outcome_ref",
            "artifact_evidence_ref",
            "artifact_member_evidence_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _checksum(getattr(self, field_name), f"publication.{field_name}"),
            )
        object.__setattr__(
            self,
            "committed_at",
            _aware_datetime(self.committed_at, "publication.committed_at"),
        )
        object.__setattr__(
            self,
            "metadata",
            _metadata(self.metadata, "publication.metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "publication_authority_ref": self.publication_authority_ref,
            "terminal_side_effect_outcome_ref": self.terminal_side_effect_outcome_ref,
            "artifact_evidence_ref": self.artifact_evidence_ref,
            "artifact_member_evidence_ref": self.artifact_member_evidence_ref,
            "committed_at": format_datetime(self.committed_at),
            "metadata": thaw_canonical_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_keys(
            value,
            required=frozenset(
                {
                    "identity_scope_ref",
                    "subject_scope_ref",
                    "publication_authority_ref",
                    "terminal_side_effect_outcome_ref",
                    "artifact_evidence_ref",
                    "artifact_member_evidence_ref",
                    "committed_at",
                    "metadata",
                }
            ),
            model=cls.__name__,
        )
        payload["committed_at"] = _datetime_from_json(
            payload["committed_at"],
            "publication.committed_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphTerminalArtifact:
    artifact_key: str
    artifact_id: str
    ref: str
    relative_path: str
    content_checksum: str
    byte_size: int
    media_type: str
    node_id: str
    attempt_id: str
    required_for_replay: bool
    required_for_publication: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("artifact_key", "artifact_id", "node_id", "attempt_id"):
            object.__setattr__(
                self,
                field_name,
                _identifier(getattr(self, field_name), f"artifact.{field_name}"),
            )
        object.__setattr__(self, "ref", _reference(self.ref, "artifact.ref"))
        object.__setattr__(
            self,
            "relative_path",
            _manifest_relative_path(self.relative_path, "artifact.relative_path"),
        )
        object.__setattr__(
            self,
            "content_checksum",
            _checksum(self.content_checksum, "artifact.content_checksum"),
        )
        object.__setattr__(
            self,
            "byte_size",
            _non_negative_int(self.byte_size, "artifact.byte_size"),
        )
        object.__setattr__(
            self,
            "media_type",
            _media_type(self.media_type, "artifact.media_type"),
        )
        for field_name in ("required_for_replay", "required_for_publication"):
            object.__setattr__(
                self,
                field_name,
                _boolean(getattr(self, field_name), f"artifact.{field_name}"),
            )
        object.__setattr__(self, "metadata", _metadata(self.metadata, "artifact.metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "artifact_id": self.artifact_id,
            "ref": self.ref,
            "relative_path": self.relative_path,
            "content_checksum": self.content_checksum,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "required_for_replay": self.required_for_replay,
            "required_for_publication": self.required_for_publication,
            "metadata": thaw_canonical_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **_exact_keys(
                value,
                required=frozenset(
                    {
                        "artifact_key",
                        "artifact_id",
                        "ref",
                        "relative_path",
                        "content_checksum",
                        "byte_size",
                        "media_type",
                        "node_id",
                        "attempt_id",
                        "required_for_replay",
                        "required_for_publication",
                        "metadata",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class GraphTerminalManifest:
    tenant_id: str
    run_id: str
    graph_id: str
    graph_version: str
    graph_schema_version: str
    compiler_version: str
    normalized_graph_checksum: str
    status: GraphTerminalStatus | str
    started_at: datetime
    completed_at: datetime
    terminal_state_ref: str
    checkpoint_ref: str
    terminal_node_ids: tuple[str, ...]
    gate_evidence_refs: tuple[str, ...]
    artifacts: tuple[GraphTerminalArtifact, ...] = ()
    publication: GraphTerminalPublicationEvidence | None = None
    schema_version: str = GRAPH_TERMINAL_MANIFEST_SCHEMA
    manifest_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "run_id", "graph_id"):
            object.__setattr__(
                self,
                field_name,
                _identifier(getattr(self, field_name), field_name),
            )
        for field_name in ("graph_version", "graph_schema_version", "compiler_version"):
            object.__setattr__(
                self,
                field_name,
                _exact_version(getattr(self, field_name), field_name),
            )
        if self.schema_version != GRAPH_TERMINAL_MANIFEST_SCHEMA:
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.SCHEMA_UNSUPPORTED,
                f"unsupported Graph terminal manifest schema: {self.schema_version}",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "normalized_graph_checksum",
            _checksum(self.normalized_graph_checksum, "normalized_graph_checksum"),
        )
        try:
            status = GraphTerminalStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise _schema_error("status") from exc
        object.__setattr__(self, "status", status)
        started_at = _aware_datetime(self.started_at, "started_at")
        completed_at = _aware_datetime(self.completed_at, "completed_at")
        if completed_at < started_at:
            raise _schema_error("completed_at")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(
            self,
            "terminal_state_ref",
            _checksum(self.terminal_state_ref, "terminal_state_ref"),
        )
        object.__setattr__(
            self,
            "checkpoint_ref",
            _reference(self.checkpoint_ref, "checkpoint_ref"),
        )
        object.__setattr__(
            self,
            "terminal_node_ids",
            _stable_tuple(
                self.terminal_node_ids,
                "terminal_node_ids",
                normalize=_identifier,
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "gate_evidence_refs",
            _stable_tuple(
                self.gate_evidence_refs,
                "gate_evidence_refs",
                normalize=_checksum,
                allow_empty=False,
            ),
        )
        artifacts = _artifacts(self.artifacts)
        object.__setattr__(self, "artifacts", artifacts)
        publication = self.publication
        if publication is not None and not isinstance(
            publication,
            GraphTerminalPublicationEvidence,
        ):
            if not isinstance(publication, Mapping):
                raise _schema_error("publication")
            publication = GraphTerminalPublicationEvidence.from_dict(publication)
        object.__setattr__(self, "publication", publication)
        if publication is not None:
            if not started_at <= publication.committed_at <= completed_at:
                raise _schema_error("publication.committed_at")
            if not artifacts or not any(
                artifact.required_for_publication for artifact in artifacts
            ):
                raise _schema_error("publication.artifacts")

        supplied_hash = self.manifest_hash
        expected_hash = checksum_for(self.content_projection())
        if supplied_hash is not None:
            supplied_hash = _checksum(supplied_hash, "manifest_hash")
            if supplied_hash != expected_hash:
                raise GraphTerminalManifestError(
                    GraphTerminalManifestErrorCode.HASH_MISMATCH,
                    "Graph terminal manifest hash does not match canonical content",
                    field="manifest_hash",
                )
        object.__setattr__(self, "manifest_hash", expected_hash)

    def content_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "normalized_graph_checksum": self.normalized_graph_checksum,
            "status": self.status.value,
            "started_at": format_datetime(self.started_at),
            "completed_at": format_datetime(self.completed_at),
            "terminal_state_ref": self.terminal_state_ref,
            "checkpoint_ref": self.checkpoint_ref,
            "terminal_node_ids": list(self.terminal_node_ids),
            "gate_evidence_refs": list(self.gate_evidence_refs),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "publication": (
                self.publication.to_dict() if self.publication is not None else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.content_projection(), "manifest_hash": self.manifest_hash}

    def artifact(self, artifact_key: str) -> GraphTerminalArtifact | None:
        normalized = _identifier(artifact_key, "artifact_key")
        for artifact in self.artifacts:
            if artifact.artifact_key == normalized:
                return artifact
        return None

    def with_artifact(self, artifact: GraphTerminalArtifact) -> Self:
        if not isinstance(artifact, GraphTerminalArtifact):
            raise TypeError("artifact must be GraphTerminalArtifact")
        if self.artifact(artifact.artifact_key) is not None:
            raise _schema_error("artifacts.artifact_key")
        return replace(
            self,
            artifacts=(*self.artifacts, artifact),
            manifest_hash=None,
        )

    def without_artifact(self, artifact_key: str) -> Self:
        normalized = _identifier(artifact_key, "artifact_key")
        remaining = tuple(
            artifact
            for artifact in self.artifacts
            if artifact.artifact_key != normalized
        )
        if len(remaining) == len(self.artifacts):
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.ARTIFACT_NOT_FOUND,
                f"Graph terminal manifest artifact not found: {normalized}",
                field="artifact_key",
            )
        return replace(self, artifacts=remaining, manifest_hash=None)

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        expected_run_id: str | None = None,
    ) -> Self:
        payload = _exact_keys(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "tenant_id",
                    "run_id",
                    "graph_id",
                    "graph_version",
                    "graph_schema_version",
                    "compiler_version",
                    "normalized_graph_checksum",
                    "status",
                    "started_at",
                    "completed_at",
                    "terminal_state_ref",
                    "checkpoint_ref",
                    "terminal_node_ids",
                    "gate_evidence_refs",
                    "artifacts",
                    "publication",
                    "manifest_hash",
                }
            ),
            model=cls.__name__,
        )
        if payload["schema_version"] != GRAPH_TERMINAL_MANIFEST_SCHEMA:
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.SCHEMA_UNSUPPORTED,
                f"unsupported Graph terminal manifest schema: {payload['schema_version']}",
                field="schema_version",
            )
        payload["started_at"] = _datetime_from_json(payload["started_at"], "started_at")
        payload["completed_at"] = _datetime_from_json(
            payload["completed_at"],
            "completed_at",
        )
        raw_artifacts = payload["artifacts"]
        if isinstance(raw_artifacts, (str, bytes, bytearray)) or not isinstance(
            raw_artifacts,
            Sequence,
        ):
            raise _schema_error("artifacts")
        payload["artifacts"] = tuple(
            GraphTerminalArtifact.from_dict(item)
            for item in raw_artifacts
            if isinstance(item, Mapping)
        )
        if len(payload["artifacts"]) != len(raw_artifacts):
            raise _schema_error("artifacts")
        raw_publication = payload["publication"]
        if raw_publication is not None:
            if not isinstance(raw_publication, Mapping):
                raise _schema_error("publication")
            payload["publication"] = GraphTerminalPublicationEvidence.from_dict(
                raw_publication
            )
        manifest = cls(**payload)
        if expected_run_id is not None:
            expected = _identifier(expected_run_id, "expected_run_id")
            if manifest.run_id != expected:
                raise GraphTerminalManifestError(
                    GraphTerminalManifestErrorCode.IDENTITY_MISMATCH,
                    "Graph terminal manifest run identity does not match",
                    field="run_id",
                )
        return manifest


@dataclass(frozen=True, slots=True)
class GraphTerminalManifestCommitRequest:
    """Harness-decided terminal state ready for one artifact visibility commit."""

    context: GraphTerminalManifestContext
    run_id: str
    status: GraphTerminalStatus | str
    completed_at: datetime
    terminal_state_ref: str
    gate_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.context, GraphTerminalManifestContext):
            raise TypeError("context must be GraphTerminalManifestContext")
        object.__setattr__(self, "run_id", _identifier(self.run_id, "run_id"))
        try:
            status = GraphTerminalStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise _schema_error("status") from exc
        if status is GraphTerminalStatus.SUCCEEDED:
            raise _schema_error("status")
        object.__setattr__(self, "status", status)
        completed_at = _aware_datetime(self.completed_at, "completed_at")
        if completed_at < self.context.started_at:
            raise _schema_error("completed_at")
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(
            self,
            "terminal_state_ref",
            _checksum(self.terminal_state_ref, "terminal_state_ref"),
        )
        object.__setattr__(
            self,
            "gate_evidence_refs",
            _stable_tuple(
                self.gate_evidence_refs,
                "gate_evidence_refs",
                normalize=_checksum,
                allow_empty=False,
            ),
        )

    def to_manifest(
        self,
        *,
        artifacts: tuple[GraphTerminalArtifact, ...],
    ) -> GraphTerminalManifest:
        return GraphTerminalManifest(
            tenant_id=self.context.tenant_id,
            run_id=self.run_id,
            graph_id=self.context.graph_id,
            graph_version=self.context.graph_version,
            graph_schema_version=self.context.graph_schema_version,
            compiler_version=self.context.compiler_version,
            normalized_graph_checksum=self.context.normalized_graph_checksum,
            status=self.status,
            started_at=self.context.started_at,
            completed_at=self.completed_at,
            terminal_state_ref=self.terminal_state_ref,
            checkpoint_ref=(
                f"graph-state://{self.run_id}/"
                f"{self.terminal_state_ref.removeprefix('sha256:')}"
            ),
            terminal_node_ids=self.context.terminal_node_ids,
            gate_evidence_refs=self.gate_evidence_refs,
            artifacts=artifacts,
            publication=None,
        )


def parse_graph_terminal_manifest(
    value: Mapping[str, Any],
    *,
    expected_run_id: str,
) -> GraphTerminalManifest:
    expected = _identifier(expected_run_id, "expected_run_id")
    if not isinstance(value, Mapping):
        raise _schema_error("manifest")
    schema = value.get("schema_version")
    if isinstance(schema, str) and schema.startswith("newsroom.workflow_run_manifest."):
        raise GraphTerminalManifestHistoryError(
            GraphManifestHistoryDiagnostic(
                run_id=expected,
                observed_schema=schema,
            )
        )
    if schema != GRAPH_TERMINAL_MANIFEST_SCHEMA:
        raise GraphTerminalManifestError(
            GraphTerminalManifestErrorCode.SCHEMA_UNSUPPORTED,
            f"unsupported Graph terminal manifest schema: {schema}",
            field="schema_version",
        )
    return GraphTerminalManifest.from_dict(value, expected_run_id=expected)


def graph_terminal_manifest_hash(
    value: GraphTerminalManifest | Mapping[str, Any],
) -> str:
    manifest = (
        value
        if isinstance(value, GraphTerminalManifest)
        else GraphTerminalManifest.from_dict(value)
    )
    return checksum_for(manifest.content_projection())


@runtime_checkable
class GraphArtifactContentPort(Protocol):
    """Physical reader that enforces the shared artifact path boundary."""

    def read_artifact_content(self, *, run_id: str, relative_path: str) -> bytes:
        ...


@runtime_checkable
class GraphTerminalManifestPort(Protocol):
    """Atomic owner port for canonical Graph terminal manifest authority."""

    def read_terminal_manifest(self, run_id: str) -> GraphTerminalManifest:
        ...

    def write_terminal_manifest(
        self,
        manifest: GraphTerminalManifest,
    ) -> GraphTerminalManifest:
        ...

    def replace_terminal_manifest(
        self,
        manifest: GraphTerminalManifest,
        *,
        expected_manifest_hash: str,
    ) -> GraphTerminalManifest:
        ...


@runtime_checkable
class GraphTerminalManifestRecorderPort(Protocol):
    """Commit an unpublished terminal record after Harness reaches failure."""

    def commit_unpublished_terminal_manifest(
        self,
        request: GraphTerminalManifestCommitRequest,
    ) -> GraphTerminalManifest:
        ...


@runtime_checkable
class GraphArtifactStagingPort(Protocol):
    """Non-authoritative metadata used before one terminal visibility commit."""

    def stage_artifact(
        self,
        *,
        run_id: str,
        artifact: GraphTerminalArtifact,
    ) -> GraphTerminalArtifact:
        ...

    def read_staged_artifact(
        self,
        *,
        run_id: str,
        artifact_key: str,
    ) -> GraphTerminalArtifact:
        ...

    def list_staged_artifacts(self, run_id: str) -> tuple[GraphTerminalArtifact, ...]:
        ...


@dataclass(frozen=True, slots=True)
class GraphArtifactContentRecord:
    artifact_key: str
    artifact_id: str
    ref: str
    relative_path: str
    media_type: str
    byte_size: int
    content_checksum: str
    content: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "artifact_id": self.artifact_id,
            "ref": self.ref,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "content_checksum": self.content_checksum,
            "content": self.content,
        }


class GraphArtifactStrictContentReader:
    def __init__(
        self,
        content_port: GraphArtifactContentPort,
        *,
        max_content_bytes: int = MAX_GRAPH_ARTIFACT_CONTENT_BYTES,
    ) -> None:
        if not isinstance(content_port, GraphArtifactContentPort):
            raise TypeError("content_port must implement GraphArtifactContentPort")
        if (
            isinstance(max_content_bytes, bool)
            or not isinstance(max_content_bytes, int)
            or max_content_bytes <= 0
        ):
            raise ValueError("max_content_bytes must be a positive integer")
        self.content_port = content_port
        self.max_content_bytes = max_content_bytes

    def read(
        self,
        manifest: GraphTerminalManifest,
        artifact_key: str,
        *,
        redact: bool = True,
    ) -> GraphArtifactContentRecord:
        if not isinstance(manifest, GraphTerminalManifest):
            raise TypeError("manifest must be GraphTerminalManifest")
        artifact = manifest.artifact(artifact_key)
        if artifact is None:
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.ARTIFACT_NOT_FOUND,
                f"Graph terminal manifest artifact not found: {artifact_key}",
                field="artifact_key",
            )
        content = self.content_port.read_artifact_content(
            run_id=manifest.run_id,
            relative_path=artifact.relative_path,
        )
        if not isinstance(content, bytes):
            raise TypeError("content port must return bytes")
        if len(content) > self.max_content_bytes:
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.ARTIFACT_CONTENT_TOO_LARGE,
                "Graph artifact content exceeds the strict reader limit",
                field="artifact.byte_size",
            )
        if len(content) != artifact.byte_size:
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.ARTIFACT_SIZE_MISMATCH,
                "Graph artifact content size does not match terminal manifest",
                field="artifact.byte_size",
            )
        actual_checksum = f"sha256:{sha256(content).hexdigest()}"
        if actual_checksum != artifact.content_checksum:
            raise GraphTerminalManifestError(
                GraphTerminalManifestErrorCode.ARTIFACT_CHECKSUM_MISMATCH,
                "Graph artifact content checksum does not match terminal manifest",
                field="artifact.content_checksum",
            )
        decoded = _decode_content(content, artifact.media_type)
        if redact:
            decoded = _redact_sensitive_values(decoded)
        return GraphArtifactContentRecord(
            artifact_key=artifact.artifact_key,
            artifact_id=artifact.artifact_id,
            ref=artifact.ref,
            relative_path=artifact.relative_path,
            media_type=artifact.media_type,
            byte_size=artifact.byte_size,
            content_checksum=artifact.content_checksum,
            content=decoded,
        )


def _artifacts(values: Sequence[GraphTerminalArtifact]) -> tuple[GraphTerminalArtifact, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise _schema_error("artifacts")
    if len(values) > MAX_GRAPH_TERMINAL_ARTIFACTS:
        raise _schema_error("artifacts")
    normalized: list[GraphTerminalArtifact] = []
    for value in values:
        if isinstance(value, GraphTerminalArtifact):
            normalized.append(value)
        elif isinstance(value, Mapping):
            normalized.append(GraphTerminalArtifact.from_dict(value))
        else:
            raise _schema_error("artifacts")
    identities = (
        [item.artifact_key for item in normalized],
        [item.artifact_id for item in normalized],
        [item.ref for item in normalized],
        [item.relative_path for item in normalized],
    )
    if any(len(values) != len(set(values)) for values in identities):
        raise _schema_error("artifacts.identity")
    return tuple(sorted(normalized, key=lambda item: item.artifact_key))


def _decode_content(content: bytes, media_type: str) -> Any:
    try:
        if media_type == "application/json":
            return json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        if media_type == "application/x-ndjson":
            values = []
            for line_number, line in enumerate(content.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    values.append(
                        json.loads(
                            line.decode("utf-8"),
                            object_pairs_hook=_unique_json_object,
                            parse_constant=_reject_json_constant,
                        )
                    )
                except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid NDJSON line {line_number}") from exc
            return values
        if media_type.startswith("text/"):
            return content.decode("utf-8")
        return content
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise GraphTerminalManifestError(
            GraphTerminalManifestErrorCode.ARTIFACT_CONTENT_INVALID,
            "Graph artifact content does not match its declared media type",
            field="artifact.media_type",
        ) from exc


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[redacted]"
                if _is_sensitive_key(str(key))
                else _redact_sensitive_values(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    return value


def _metadata(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _schema_error(field_name)
    _reject_sensitive_metadata(value, field_name)
    try:
        normalized = normalize_canonical_json(value, path=f"$.{field_name}")
        if not isinstance(normalized, Mapping):
            raise TypeError("metadata did not remain an object")
        if len(canonical_json_bytes(normalized)) > MAX_GRAPH_TERMINAL_METADATA_BYTES:
            raise ValueError("metadata exceeds limit")
    except (TypeError, ValueError) as exc:
        raise _schema_error(field_name) from exc
    return MappingProxyType(dict(normalized))


def _reject_sensitive_metadata(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                raise _schema_error(field_name)
            _reject_sensitive_metadata(item, field_name)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_sensitive_metadata(item, field_name)


def _is_sensitive_key(value: str) -> bool:
    normalized = value.casefold()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _manifest_relative_path(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name, max_length=2048)
    normalized = text.replace("\\", "/")
    raw_parts = normalized.split("/")
    windows = PureWindowsPath(text)
    posix = PurePosixPath(normalized)
    if (
        any(part in {"", ".", ".."} for part in raw_parts)
        or windows.is_absolute()
        or windows.drive
        or posix.is_absolute()
        or not posix.parts
    ):
        raise _schema_error(field_name)
    for part in posix.parts:
        if (
            any(ord(character) < 32 or ord(character) == 127 for character in part)
            or any(character in _WINDOWS_RESERVED_CHARACTERS for character in part)
            or part.endswith((".", " "))
            or _DOS_DEVICE_NAME.fullmatch(part)
        ):
            raise _schema_error(field_name)
    return posix.as_posix()


def _stable_tuple(
    values: Sequence[Any],
    field_name: str,
    *,
    normalize,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise _schema_error(field_name)
    normalized = tuple(normalize(value, field_name) for value in values)
    if (not allow_empty and not normalized) or len(normalized) != len(set(normalized)):
        raise _schema_error(field_name)
    return tuple(sorted(normalized))


def _exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _schema_error(model)
    if frozenset(value) != required:
        raise _schema_error(model)
    return dict(value)


def _required_text(value: Any, field_name: str, *, max_length: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
    ):
        raise _schema_error(field_name)
    return value


def _identifier(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if _IDENTIFIER.fullmatch(text) is None:
        raise _schema_error(field_name)
    return text


def _exact_version(value: Any, field_name: str) -> str:
    text = _identifier(value, field_name)
    if text.casefold() in _MOVING_VERSIONS:
        raise _schema_error(field_name)
    return text


def _reference(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name, max_length=2048)
    if _REFERENCE.fullmatch(text) is None:
        raise _schema_error(field_name)
    return text


def _checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if _CHECKSUM.fullmatch(text) is None:
        raise _schema_error(field_name)
    return text


def _media_type(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name, max_length=255).casefold()
    if _MEDIA_TYPE.fullmatch(text) is None:
        raise _schema_error(field_name)
    return text


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _schema_error(field_name)
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise _schema_error(field_name)
    return value


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _schema_error(field_name)
    return ensure_utc(value)


def _datetime_from_json(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise _schema_error(field_name)
    parsed = parse_datetime(value)
    if parsed is None:
        raise _schema_error(field_name)
    return _aware_datetime(parsed, field_name)


def _schema_error(field_name: str) -> GraphTerminalManifestError:
    return GraphTerminalManifestError(
        GraphTerminalManifestErrorCode.SCHEMA_INVALID,
        f"invalid Graph terminal manifest field: {field_name}",
        field=field_name,
    )


__all__ = [
    "GRAPH_TERMINAL_MANIFEST_SCHEMA",
    "GraphArtifactContentPort",
    "GraphArtifactContentRecord",
    "GraphArtifactStagingPort",
    "GraphArtifactStrictContentReader",
    "GraphManifestHistoryDiagnostic",
    "GraphTerminalArtifact",
    "GraphTerminalManifest",
    "GraphTerminalManifestCommitRequest",
    "GraphTerminalManifestContext",
    "GraphTerminalManifestError",
    "GraphTerminalManifestErrorCode",
    "GraphTerminalManifestHistoryError",
    "GraphTerminalManifestPort",
    "GraphTerminalManifestRecorderPort",
    "GraphTerminalPublicationEvidence",
    "GraphTerminalStatus",
    "graph_terminal_manifest_hash",
    "parse_graph_terminal_manifest",
]
