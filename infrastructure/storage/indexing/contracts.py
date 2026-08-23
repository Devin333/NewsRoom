from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, Self, runtime_checkable

from framework.agent.artifacts.paths import validate_relative_artifact_path
from framework.events.canonical import (
    StoredEvent,
    checksum_for,
)
from framework.events.projection import GraphEventContext, GraphRunIdentity
from framework.harness.artifacts.terminal_manifest import (
    GraphTerminalArtifact,
    GraphTerminalManifest,
    graph_terminal_manifest_hash,
)
from framework.shared.time import format_datetime, parse_datetime


GRAPH_STORAGE_INDEX_IDENTITY_SCHEMA = (
    "newsroom.graph-storage-index-identity/v1"
)
GRAPH_ARTIFACT_NODE_BINDING_SCHEMA = (
    "newsroom.graph-artifact-node-binding/v1"
)
GRAPH_ARTIFACT_INDEX_RECORD_SCHEMA = (
    "newsroom.graph-artifact-index-record/v1"
)
GRAPH_EVENT_INDEX_RECORD_SCHEMA = "newsroom.graph-event-index-record/v1"
GRAPH_STORAGE_INDEX_CANDIDATE_REQUEST_SCHEMA = (
    "newsroom.graph-storage-index-candidate-request/v1"
)
GRAPH_STORAGE_INDEX_CANDIDATE_SCHEMA = (
    "newsroom.graph-storage-index-candidate/v1"
)
GRAPH_STORAGE_INDEX_DIAGNOSTIC_SCHEMA = (
    "newsroom.graph-storage-index-diagnostic/v1"
)
GRAPH_STORAGE_INDEX_DRY_RUN_SCHEMA = (
    "newsroom.graph-storage-index-dry-run/v1"
)
GRAPH_STORAGE_INDEX_STAGE_RECEIPT_SCHEMA = (
    "newsroom.graph-storage-index-stage-receipt/v1"
)

MAX_GRAPH_INDEX_ARTIFACTS = 10_000
MAX_GRAPH_INDEX_EVENTS = 100_000
_SHA256_PREFIX = "sha256:"


class GraphIndexDiagnosticCode(StrEnum):
    MANIFEST_INTEGRITY_INVALID = "graph_index_manifest_integrity_invalid"
    EVENT_HISTORY_EMPTY = "graph_index_event_history_empty"
    EVENT_INTEGRITY_INVALID = "graph_index_event_integrity_invalid"
    EVENT_SCOPE_MISMATCH = "graph_index_event_scope_mismatch"
    EVENT_SEQUENCE_INVALID = "graph_index_event_sequence_invalid"
    EVENT_CONTEXT_INVALID = "graph_index_event_context_invalid"
    EVENT_GRAPH_IDENTITY_MISMATCH = (
        "graph_index_event_graph_identity_mismatch"
    )
    NODE_INSTANCE_CONFLICT = "graph_index_node_instance_conflict"
    ARTIFACT_BINDING_MISSING = "graph_index_artifact_binding_missing"
    ARTIFACT_BINDING_EXTRA = "graph_index_artifact_binding_extra"
    ARTIFACT_BINDING_DUPLICATE = "graph_index_artifact_binding_duplicate"
    ARTIFACT_BINDING_MISMATCH = "graph_index_artifact_binding_mismatch"
    ARTIFACT_NODE_INSTANCE_UNVERIFIED = (
        "graph_index_artifact_node_instance_unverified"
    )
    ARTIFACT_PATH_INVALID = "graph_index_artifact_path_invalid"


class GraphIndexStageStatus(StrEnum):
    STAGED = "staged"
    IDEMPOTENT = "idempotent"


class GraphStorageIndexErrorCode(StrEnum):
    REQUEST_INVALID = "graph_storage_index_request_invalid"
    CANDIDATE_NOT_QUALIFIED = "graph_storage_index_candidate_not_qualified"
    CANDIDATE_CONFLICT = "graph_storage_index_candidate_conflict"
    CANDIDATE_NOT_FOUND = "graph_storage_index_candidate_not_found"
    CANDIDATE_CORRUPT = "graph_storage_index_candidate_corrupt"
    CANDIDATE_SCOPE_MISMATCH = "graph_storage_index_candidate_scope_mismatch"
    INDEX_CONFLICT = "graph_storage_index_conflict"
    INDEX_NOT_FOUND = "graph_storage_index_not_found"
    INDEX_CORRUPT = "graph_storage_index_corrupt"
    INDEX_SCOPE_MISMATCH = "graph_storage_index_scope_mismatch"


class GraphStorageIndexError(ValueError):
    def __init__(
        self,
        code: GraphStorageIndexErrorCode | str,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        self.code = GraphStorageIndexErrorCode(code)
        self.field = field
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GraphStorageIndexIdentity:
    tenant_id: str
    graph_identity: GraphRunIdentity
    terminal_manifest_hash: str
    schema_version: str = GRAPH_STORAGE_INDEX_IDENTITY_SCHEMA
    identity_ref: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_id",
            _required_text(self.tenant_id, "tenant_id"),
        )
        if not isinstance(self.graph_identity, GraphRunIdentity):
            raise TypeError("graph_identity must be GraphRunIdentity")
        object.__setattr__(
            self,
            "terminal_manifest_hash",
            _checksum(self.terminal_manifest_hash, "terminal_manifest_hash"),
        )
        if self.schema_version != GRAPH_STORAGE_INDEX_IDENTITY_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index identity schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "identity_ref",
            checksum_for(self.checksum_projection()),
        )

    @property
    def run_id(self) -> str:
        return self.graph_identity.run_id

    @classmethod
    def from_manifest(cls, manifest: GraphTerminalManifest) -> Self:
        if not isinstance(manifest, GraphTerminalManifest):
            raise TypeError("manifest must be GraphTerminalManifest")
        if manifest.manifest_hash is None:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph terminal manifest has no canonical hash",
                field="manifest_hash",
            )
        if manifest.manifest_hash != graph_terminal_manifest_hash(manifest):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph terminal manifest checksum is invalid",
                field="manifest_hash",
            )
        return cls(
            tenant_id=manifest.tenant_id,
            graph_identity=GraphRunIdentity(
                run_id=manifest.run_id,
                graph_id=manifest.graph_id,
                graph_version=manifest.graph_version,
                graph_schema_version=manifest.graph_schema_version,
                compiler_version=manifest.compiler_version,
                normalized_graph_checksum=manifest.normalized_graph_checksum,
            ),
            terminal_manifest_hash=manifest.manifest_hash,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "graph_identity": self.graph_identity.to_dict(),
            "terminal_manifest_hash": self.terminal_manifest_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "identity_ref": self.identity_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "tenant_id",
                "graph_identity",
                "terminal_manifest_hash",
                "identity_ref",
            },
            "Graph storage index identity",
        )
        identity = cls(
            tenant_id=payload["tenant_id"],
            graph_identity=_graph_identity_from_dict(payload["graph_identity"]),
            terminal_manifest_hash=payload["terminal_manifest_hash"],
            schema_version=payload["schema_version"],
        )
        if payload["identity_ref"] != identity.identity_ref:
            raise _corrupt("Graph storage index identity checksum is invalid")
        return identity


@dataclass(frozen=True, slots=True)
class GraphArtifactNodeBinding:
    artifact_id: str
    node_id: str
    node_instance_id: str
    attempt_id: str
    evidence_ref: str
    schema_version: str = GRAPH_ARTIFACT_NODE_BINDING_SCHEMA
    binding_ref: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "artifact_id",
            "node_id",
            "node_instance_id",
            "attempt_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "evidence_ref",
            _checksum(self.evidence_ref, "evidence_ref"),
        )
        if self.schema_version != GRAPH_ARTIFACT_NODE_BINDING_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph artifact node binding schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "binding_ref",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "attempt_id": self.attempt_id,
            "evidence_ref": self.evidence_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "binding_ref": self.binding_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "artifact_id",
                "node_id",
                "node_instance_id",
                "attempt_id",
                "evidence_ref",
                "binding_ref",
            },
            "Graph artifact node binding",
        )
        binding = cls(
            artifact_id=payload["artifact_id"],
            node_id=payload["node_id"],
            node_instance_id=payload["node_instance_id"],
            attempt_id=payload["attempt_id"],
            evidence_ref=payload["evidence_ref"],
            schema_version=payload["schema_version"],
        )
        if payload["binding_ref"] != binding.binding_ref:
            raise _corrupt("Graph artifact node binding checksum is invalid")
        return binding


@dataclass(frozen=True, slots=True)
class GraphArtifactIndexRecord:
    identity: GraphStorageIndexIdentity
    artifact_key: str
    artifact_id: str
    artifact_ref: str
    relative_path: str
    content_checksum: str
    byte_size: int
    media_type: str
    node_id: str
    node_instance_id: str
    attempt_id: str
    binding_evidence_ref: str
    required_for_replay: bool
    required_for_publication: bool
    schema_version: str = GRAPH_ARTIFACT_INDEX_RECORD_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, GraphStorageIndexIdentity):
            raise TypeError("identity must be GraphStorageIndexIdentity")
        for field_name in (
            "artifact_key",
            "artifact_id",
            "artifact_ref",
            "media_type",
            "node_id",
            "node_instance_id",
            "attempt_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "relative_path",
            validate_relative_artifact_path(
                self.relative_path,
                field="Graph artifact index relative_path",
            ),
        )
        object.__setattr__(
            self,
            "content_checksum",
            _checksum(self.content_checksum, "content_checksum"),
        )
        object.__setattr__(
            self,
            "byte_size",
            _nonnegative_int(self.byte_size, "byte_size"),
        )
        object.__setattr__(
            self,
            "binding_evidence_ref",
            _checksum(self.binding_evidence_ref, "binding_evidence_ref"),
        )
        for field_name in ("required_for_replay", "required_for_publication"):
            if not isinstance(getattr(self, field_name), bool):
                raise GraphStorageIndexError(
                    GraphStorageIndexErrorCode.REQUEST_INVALID,
                    f"{field_name} must be a boolean",
                    field=field_name,
                )
        if self.schema_version != GRAPH_ARTIFACT_INDEX_RECORD_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph artifact index record schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "record_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_artifact(
        cls,
        *,
        identity: GraphStorageIndexIdentity,
        artifact: GraphTerminalArtifact,
        binding: GraphArtifactNodeBinding,
    ) -> Self:
        if not isinstance(artifact, GraphTerminalArtifact):
            raise TypeError("artifact must be GraphTerminalArtifact")
        if not isinstance(binding, GraphArtifactNodeBinding):
            raise TypeError("binding must be GraphArtifactNodeBinding")
        if (
            binding.artifact_id != artifact.artifact_id
            or binding.node_id != artifact.node_id
            or binding.attempt_id != artifact.attempt_id
        ):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph artifact node binding changed terminal manifest identity",
                field="artifact_binding",
            )
        return cls(
            identity=identity,
            artifact_key=artifact.artifact_key,
            artifact_id=artifact.artifact_id,
            artifact_ref=artifact.ref,
            relative_path=artifact.relative_path,
            content_checksum=artifact.content_checksum,
            byte_size=artifact.byte_size,
            media_type=artifact.media_type,
            node_id=artifact.node_id,
            node_instance_id=binding.node_instance_id,
            attempt_id=artifact.attempt_id,
            binding_evidence_ref=binding.evidence_ref,
            required_for_replay=artifact.required_for_replay,
            required_for_publication=artifact.required_for_publication,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "artifact_key": self.artifact_key,
            "artifact_id": self.artifact_id,
            "artifact_ref": self.artifact_ref,
            "relative_path": self.relative_path,
            "content_checksum": self.content_checksum,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "attempt_id": self.attempt_id,
            "binding_evidence_ref": self.binding_evidence_ref,
            "required_for_replay": self.required_for_replay,
            "required_for_publication": self.required_for_publication,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "identity",
                "artifact_key",
                "artifact_id",
                "artifact_ref",
                "relative_path",
                "content_checksum",
                "byte_size",
                "media_type",
                "node_id",
                "node_instance_id",
                "attempt_id",
                "binding_evidence_ref",
                "required_for_replay",
                "required_for_publication",
                "record_checksum",
            },
            "Graph artifact index record",
        )
        record = cls(
            identity=GraphStorageIndexIdentity.from_dict(payload["identity"]),
            artifact_key=payload["artifact_key"],
            artifact_id=payload["artifact_id"],
            artifact_ref=payload["artifact_ref"],
            relative_path=payload["relative_path"],
            content_checksum=payload["content_checksum"],
            byte_size=payload["byte_size"],
            media_type=payload["media_type"],
            node_id=payload["node_id"],
            node_instance_id=payload["node_instance_id"],
            attempt_id=payload["attempt_id"],
            binding_evidence_ref=payload["binding_evidence_ref"],
            required_for_replay=payload["required_for_replay"],
            required_for_publication=payload["required_for_publication"],
            schema_version=payload["schema_version"],
        )
        if payload["record_checksum"] != record.record_checksum:
            raise _corrupt("Graph artifact index record checksum is invalid")
        return record


@dataclass(frozen=True, slots=True)
class GraphEventIndexRecord:
    identity: GraphStorageIndexIdentity
    event_id: str
    stream_id: str
    stream_sequence: int
    event_type: str
    data_schema: str
    node_id: str | None
    node_instance_id: str | None
    occurred_at: datetime
    observed_at: datetime
    content_checksum: str
    source_record_checksum: str
    schema_version: str = GRAPH_EVENT_INDEX_RECORD_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, GraphStorageIndexIdentity):
            raise TypeError("identity must be GraphStorageIndexIdentity")
        for field_name in ("event_id", "stream_id", "event_type", "data_schema"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "stream_sequence",
            _positive_int(self.stream_sequence, "stream_sequence"),
        )
        node_id = _optional_text(self.node_id, "node_id")
        node_instance_id = _optional_text(
            self.node_instance_id,
            "node_instance_id",
        )
        if (node_id is None) != (node_instance_id is None):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph event index node identity must be complete",
                field="node_instance_id",
            )
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(
            self,
            "occurred_at",
            _aware_datetime(self.occurred_at, "occurred_at"),
        )
        object.__setattr__(
            self,
            "observed_at",
            _aware_datetime(self.observed_at, "observed_at"),
        )
        object.__setattr__(
            self,
            "content_checksum",
            _checksum(self.content_checksum, "content_checksum"),
        )
        object.__setattr__(
            self,
            "source_record_checksum",
            _checksum(self.source_record_checksum, "source_record_checksum"),
        )
        if self.stream_id != f"run:{self.identity.run_id}":
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph event index record changed the run stream",
                field="stream_id",
            )
        if self.schema_version != GRAPH_EVENT_INDEX_RECORD_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph event index record schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "record_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_event(
        cls,
        *,
        identity: GraphStorageIndexIdentity,
        event: StoredEvent,
        context: GraphEventContext,
    ) -> Self:
        if not isinstance(event, StoredEvent):
            raise TypeError("event must be StoredEvent")
        if not isinstance(context, GraphEventContext):
            raise TypeError("context must be GraphEventContext")
        return cls(
            identity=identity,
            event_id=event.event_id,
            stream_id=event.stream_id,
            stream_sequence=event.stream_sequence,
            event_type=event.event_type,
            data_schema=event.data_schema,
            node_id=context.node_id,
            node_instance_id=context.node_instance_id,
            occurred_at=event.occurred_at,
            observed_at=event.observed_at,
            content_checksum=event.content_checksum,
            source_record_checksum=event.record_checksum,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "stream_sequence": self.stream_sequence,
            "event_type": self.event_type,
            "data_schema": self.data_schema,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "occurred_at": format_datetime(self.occurred_at),
            "observed_at": format_datetime(self.observed_at),
            "content_checksum": self.content_checksum,
            "source_record_checksum": self.source_record_checksum,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "identity",
                "event_id",
                "stream_id",
                "stream_sequence",
                "event_type",
                "data_schema",
                "node_id",
                "node_instance_id",
                "occurred_at",
                "observed_at",
                "content_checksum",
                "source_record_checksum",
                "record_checksum",
            },
            "Graph event index record",
        )
        record = cls(
            identity=GraphStorageIndexIdentity.from_dict(payload["identity"]),
            event_id=payload["event_id"],
            stream_id=payload["stream_id"],
            stream_sequence=payload["stream_sequence"],
            event_type=payload["event_type"],
            data_schema=payload["data_schema"],
            node_id=payload["node_id"],
            node_instance_id=payload["node_instance_id"],
            occurred_at=_datetime_from_json(payload["occurred_at"], "occurred_at"),
            observed_at=_datetime_from_json(payload["observed_at"], "observed_at"),
            content_checksum=payload["content_checksum"],
            source_record_checksum=payload["source_record_checksum"],
            schema_version=payload["schema_version"],
        )
        if payload["record_checksum"] != record.record_checksum:
            raise _corrupt("Graph event index record checksum is invalid")
        return record


@dataclass(frozen=True, slots=True)
class GraphStorageIndexCandidateRequest:
    manifest: GraphTerminalManifest
    events: tuple[StoredEvent, ...]
    artifact_bindings: tuple[GraphArtifactNodeBinding, ...]
    schema_version: str = GRAPH_STORAGE_INDEX_CANDIDATE_REQUEST_SCHEMA
    request_ref: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, GraphTerminalManifest):
            raise TypeError("manifest must be GraphTerminalManifest")
        events = _typed_tuple(self.events, StoredEvent, "events")
        bindings = _typed_tuple(
            self.artifact_bindings,
            GraphArtifactNodeBinding,
            "artifact_bindings",
        )
        if len(events) > MAX_GRAPH_INDEX_EVENTS:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index event input exceeds its bound",
                field="events",
            )
        if len(bindings) > MAX_GRAPH_INDEX_ARTIFACTS:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index binding input exceeds its bound",
                field="artifact_bindings",
            )
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "artifact_bindings", bindings)
        if self.schema_version != GRAPH_STORAGE_INDEX_CANDIDATE_REQUEST_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index candidate request schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "request_ref",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_hash": self.manifest.manifest_hash,
            "event_record_checksums": [event.record_checksum for event in self.events],
            "artifact_binding_refs": [
                binding.binding_ref for binding in self.artifact_bindings
            ],
        }


@dataclass(frozen=True, slots=True)
class GraphStorageIndexCandidate:
    identity: GraphStorageIndexIdentity
    artifact_records: tuple[GraphArtifactIndexRecord, ...]
    event_records: tuple[GraphEventIndexRecord, ...]
    schema_version: str = GRAPH_STORAGE_INDEX_CANDIDATE_SCHEMA
    event_high_watermark: int = field(init=False)
    candidate_ref: str = field(init=False)
    candidate_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, GraphStorageIndexIdentity):
            raise TypeError("identity must be GraphStorageIndexIdentity")
        artifacts = tuple(
            sorted(
                _typed_tuple(
                    self.artifact_records,
                    GraphArtifactIndexRecord,
                    "artifact_records",
                ),
                key=lambda item: (item.artifact_id, item.artifact_key),
            )
        )
        events = tuple(
            sorted(
                _typed_tuple(
                    self.event_records,
                    GraphEventIndexRecord,
                    "event_records",
                ),
                key=lambda item: item.stream_sequence,
            )
        )
        if len(artifacts) > MAX_GRAPH_INDEX_ARTIFACTS:
            raise _corrupt("Graph index candidate has too many artifact records")
        if not events or len(events) > MAX_GRAPH_INDEX_EVENTS:
            raise _corrupt("Graph index candidate event records are invalid")
        if any(item.identity != self.identity for item in (*artifacts, *events)):
            raise _corrupt("Graph index candidate contains another identity")
        _require_unique(
            (item.artifact_id for item in artifacts),
            "artifact_id",
        )
        _require_unique(
            (item.artifact_key for item in artifacts),
            "artifact_key",
        )
        _require_unique(
            (item.artifact_ref for item in artifacts),
            "artifact_ref",
        )
        _require_unique(
            (item.relative_path for item in artifacts),
            "relative_path",
        )
        _require_unique((item.event_id for item in events), "event_id")
        sequences = tuple(item.stream_sequence for item in events)
        if sequences != tuple(range(1, len(events) + 1)):
            raise _corrupt("Graph index candidate event sequence is not contiguous")
        object.__setattr__(self, "artifact_records", artifacts)
        object.__setattr__(self, "event_records", events)
        object.__setattr__(self, "event_high_watermark", sequences[-1])
        if self.schema_version != GRAPH_STORAGE_INDEX_CANDIDATE_SCHEMA:
            raise _corrupt("Graph storage index candidate schema is unsupported")
        object.__setattr__(
            self,
            "candidate_ref",
            checksum_for(
                {
                    "schema_version": self.schema_version,
                    "identity_ref": self.identity.identity_ref,
                }
            ),
        )
        object.__setattr__(
            self,
            "candidate_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "event_high_watermark": self.event_high_watermark,
            "artifact_records": [item.to_dict() for item in self.artifact_records],
            "event_records": [item.to_dict() for item in self.event_records],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "candidate_ref": self.candidate_ref,
            "candidate_checksum": self.candidate_checksum,
        }

    def verify_integrity(self) -> None:
        expected_ref = checksum_for(
            {
                "schema_version": self.schema_version,
                "identity_ref": self.identity.identity_ref,
            }
        )
        if self.candidate_ref != expected_ref:
            raise _corrupt("Graph index candidate reference is invalid")
        if self.candidate_checksum != checksum_for(self.checksum_projection()):
            raise _corrupt("Graph index candidate checksum is invalid")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "identity",
                "event_high_watermark",
                "artifact_records",
                "event_records",
                "candidate_ref",
                "candidate_checksum",
            },
            "Graph storage index candidate",
        )
        artifacts = _mapping_sequence(
            payload["artifact_records"],
            "artifact_records",
        )
        events = _mapping_sequence(payload["event_records"], "event_records")
        candidate = cls(
            identity=GraphStorageIndexIdentity.from_dict(payload["identity"]),
            artifact_records=tuple(
                GraphArtifactIndexRecord.from_dict(item) for item in artifacts
            ),
            event_records=tuple(GraphEventIndexRecord.from_dict(item) for item in events),
            schema_version=payload["schema_version"],
        )
        if payload["event_high_watermark"] != candidate.event_high_watermark:
            raise _corrupt("Graph index candidate watermark is invalid")
        if payload["candidate_ref"] != candidate.candidate_ref:
            raise _corrupt("Graph index candidate reference is invalid")
        if payload["candidate_checksum"] != candidate.candidate_checksum:
            raise _corrupt("Graph index candidate checksum is invalid")
        return candidate


@dataclass(frozen=True, slots=True)
class GraphIndexDryRunDiagnostic:
    code: GraphIndexDiagnosticCode | str
    subject_kind: str
    subject_ref: str
    detail_code: str
    schema_version: str = GRAPH_STORAGE_INDEX_DIAGNOSTIC_SCHEMA
    diagnostic_ref: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", GraphIndexDiagnosticCode(self.code))
        for field_name in ("subject_kind", "subject_ref", "detail_code"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.schema_version != GRAPH_STORAGE_INDEX_DIAGNOSTIC_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index diagnostic schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "diagnostic_ref",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "code": self.code.value,
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "detail_code": self.detail_code,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "diagnostic_ref": self.diagnostic_ref}


@dataclass(frozen=True, slots=True)
class GraphStorageIndexDryRunReport:
    request_ref: str
    diagnostics: tuple[GraphIndexDryRunDiagnostic, ...]
    candidate: GraphStorageIndexCandidate | None = None
    schema_version: str = GRAPH_STORAGE_INDEX_DRY_RUN_SCHEMA
    report_ref: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_ref",
            _checksum(self.request_ref, "request_ref"),
        )
        diagnostics = tuple(
            sorted(
                _typed_tuple(
                    self.diagnostics,
                    GraphIndexDryRunDiagnostic,
                    "diagnostics",
                ),
                key=lambda item: (
                    item.code.value,
                    item.subject_kind,
                    item.subject_ref,
                    item.detail_code,
                ),
            )
        )
        object.__setattr__(self, "diagnostics", diagnostics)
        if self.candidate is not None and not isinstance(
            self.candidate,
            GraphStorageIndexCandidate,
        ):
            raise TypeError("candidate must be GraphStorageIndexCandidate")
        if (self.candidate is None) == (not diagnostics):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph index dry-run must contain either a candidate or diagnostics",
                field="candidate",
            )
        if self.schema_version != GRAPH_STORAGE_INDEX_DRY_RUN_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph storage index dry-run schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(self, "report_ref", checksum_for(self.checksum_projection()))

    @property
    def qualified(self) -> bool:
        return self.candidate is not None

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_ref": self.request_ref,
            "qualified": self.qualified,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "candidate": self.candidate.to_dict() if self.candidate else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "report_ref": self.report_ref}


@dataclass(frozen=True, slots=True)
class GraphIndexCandidateStageReceipt:
    candidate_ref: str
    candidate_checksum: str
    storage_ref: str
    status: GraphIndexStageStatus | str
    schema_version: str = GRAPH_STORAGE_INDEX_STAGE_RECEIPT_SCHEMA
    receipt_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_ref",
            _checksum(self.candidate_ref, "candidate_ref"),
        )
        object.__setattr__(
            self,
            "candidate_checksum",
            _checksum(self.candidate_checksum, "candidate_checksum"),
        )
        object.__setattr__(
            self,
            "storage_ref",
            _required_text(self.storage_ref, "storage_ref"),
        )
        object.__setattr__(self, "status", GraphIndexStageStatus(self.status))
        if self.schema_version != GRAPH_STORAGE_INDEX_STAGE_RECEIPT_SCHEMA:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph index stage receipt schema is unsupported",
                field="schema_version",
            )
        object.__setattr__(
            self,
            "receipt_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_ref": self.candidate_ref,
            "candidate_checksum": self.candidate_checksum,
            "storage_ref": self.storage_ref,
            "status": self.status.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_checksum": self.receipt_checksum}


@runtime_checkable
class GraphIndexCandidateStorePort(Protocol):
    def stage_candidate(
        self,
        candidate: GraphStorageIndexCandidate,
    ) -> GraphIndexCandidateStageReceipt: ...

    def read_candidate(self, candidate_ref: str) -> GraphStorageIndexCandidate: ...


def _graph_identity_from_dict(value: Any) -> GraphRunIdentity:
    payload = _exact_mapping(
        value,
        {
            "run_id",
            "graph_id",
            "graph_version",
            "graph_schema_version",
            "compiler_version",
            "normalized_graph_checksum",
        },
        "Graph run identity",
    )
    return GraphRunIdentity(
        run_id=payload["run_id"],
        graph_id=payload["graph_id"],
        graph_version=payload["graph_version"],
        graph_schema_version=payload["graph_schema_version"],
        compiler_version=payload["compiler_version"],
        normalized_graph_checksum=payload["normalized_graph_checksum"],
    )


def _required_text(value: Any, field_name: str, *, max_length: int = 2_048) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            f"{field_name} must be non-empty trimmed text",
            field=field_name,
        )
    if len(value) > max_length or any(ord(character) < 32 for character in value):
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            f"{field_name} is outside its text boundary",
            field=field_name,
        )
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    return None if value is None else _required_text(value, field_name)


def _checksum(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name, max_length=71)
    digest = normalized.removeprefix(_SHA256_PREFIX)
    if (
        not normalized.startswith(_SHA256_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            f"{field_name} must be a sha256 checksum",
            field=field_name,
        )
    return normalized


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            f"{field_name} must be a positive integer",
            field=field_name,
        )
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            f"{field_name} must be a non-negative integer",
            field=field_name,
        )
    return value


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            f"{field_name} must be timezone-aware",
            field=field_name,
        )
    parsed = parse_datetime(value)
    assert parsed is not None
    return parsed


def _datetime_from_json(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise _corrupt(f"Graph index {field_name} must be serialized text")
    parsed = parse_datetime(value)
    if parsed is None:
        raise _corrupt(f"Graph index {field_name} is invalid")
    return parsed


def _typed_tuple(
    values: Sequence[Any],
    expected_type: type[Any],
    field_name: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    normalized = tuple(values)
    if any(not isinstance(value, expected_type) for value in normalized):
        raise TypeError(f"{field_name} must contain only {expected_type.__name__}")
    return normalized


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise _corrupt(f"Graph index {field_name} must be an array")
    normalized = tuple(value)
    if any(not isinstance(item, Mapping) for item in normalized):
        raise _corrupt(f"Graph index {field_name} contains a non-object")
    return normalized


def _require_unique(values: Any, field_name: str) -> None:
    normalized = tuple(values)
    if len(normalized) != len(set(normalized)):
        raise _corrupt(f"Graph index candidate contains duplicate {field_name}")


def _exact_mapping(
    value: Any,
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise _corrupt(f"{model} fields are invalid")
    return dict(value)


def _corrupt(message: str) -> GraphStorageIndexError:
    return GraphStorageIndexError(
        GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
        message,
    )


__all__ = [
    "GRAPH_ARTIFACT_INDEX_RECORD_SCHEMA",
    "GRAPH_ARTIFACT_NODE_BINDING_SCHEMA",
    "GRAPH_EVENT_INDEX_RECORD_SCHEMA",
    "GRAPH_STORAGE_INDEX_CANDIDATE_REQUEST_SCHEMA",
    "GRAPH_STORAGE_INDEX_CANDIDATE_SCHEMA",
    "GRAPH_STORAGE_INDEX_DIAGNOSTIC_SCHEMA",
    "GRAPH_STORAGE_INDEX_DRY_RUN_SCHEMA",
    "GRAPH_STORAGE_INDEX_IDENTITY_SCHEMA",
    "GRAPH_STORAGE_INDEX_STAGE_RECEIPT_SCHEMA",
    "GraphArtifactIndexRecord",
    "GraphArtifactNodeBinding",
    "GraphEventIndexRecord",
    "GraphIndexCandidateStageReceipt",
    "GraphIndexCandidateStorePort",
    "GraphIndexDiagnosticCode",
    "GraphIndexDryRunDiagnostic",
    "GraphIndexStageStatus",
    "GraphStorageIndexCandidate",
    "GraphStorageIndexCandidateRequest",
    "GraphStorageIndexDryRunReport",
    "GraphStorageIndexError",
    "GraphStorageIndexErrorCode",
    "GraphStorageIndexIdentity",
    "MAX_GRAPH_INDEX_ARTIFACTS",
    "MAX_GRAPH_INDEX_EVENTS",
]
