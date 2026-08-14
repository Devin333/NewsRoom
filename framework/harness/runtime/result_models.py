from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from framework.events.canonical import canonical_json_bytes
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    boolean,
    canonical_mapping,
    checksum,
    datetime_from_json,
    datetime_to_json,
    enum_value,
    estimated_tokens,
    exact_keys,
    exact_reference,
    identifier,
    media_type,
    non_negative_int,
    optional_text,
    reference,
    required_text,
    stable_tuple,
    thaw_mapping,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultErrorCode,
    result_error,
)


class NodeResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    HALTED = "halted"


class ArtifactClass(StrEnum):
    CONTROL = "control"
    EVIDENCE = "evidence"
    TRANSCRIPT = "transcript"
    INTERMEDIATE = "intermediate"
    REPORT = "report"
    DEBUG = "debug"


class RetentionClass(StrEnum):
    EPHEMERAL = "ephemeral"
    RUN = "run"
    EVIDENCE = "evidence"
    REPORT = "report"
    CACHE = "cache"


class ResultSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    SECRET = "secret"


class PersistenceMode(StrEnum):
    INLINE = "inline"
    ARTIFACT = "artifact"
    CACHE = "cache"
    OMITTED = "omitted"


class PersistenceReason(StrEnum):
    BELOW_INLINE_THRESHOLD = "below_inline_threshold"
    LARGE_PAYLOAD = "large_payload"
    REQUIRED_EVIDENCE = "required_evidence"
    REQUIRED_TRANSCRIPT = "required_transcript"
    REQUIRED_REPORT = "required_report"
    REQUIRED_FOR_REPLAY = "required_for_replay"
    REQUIRED_FOR_PUBLICATION = "required_for_publication"
    REUSABLE_DETERMINISTIC_RESULT = "reusable_deterministic_result"
    QUOTA_EXCEEDED = "quota_exceeded"


class ContextPolicy(StrEnum):
    SUMMARY_ONLY = "summary_only"
    SAMPLE_ALLOWED = "sample_allowed"
    REF_LOAD_ALLOWED = "ref_load_allowed"


class ContextLoadMode(StrEnum):
    SUMMARY_ONLY = "summary_only"
    SAMPLE = "sample"
    FULL = "full"


class ContextPurpose(StrEnum):
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPAIR = "repair"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class NodeResultBinding:
    tenant_id: str
    tenant_scope_ref: str
    run_id: str
    graph_id: str
    graph_version: str
    node_id: str
    attempt_id: str
    parent_checkpoint_ref: str

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "run_id", "graph_id", "node_id", "attempt_id"):
            object.__setattr__(self, field_name, identifier(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "tenant_scope_ref",
            checksum(self.tenant_scope_ref, "tenant_scope_ref"),
        )
        object.__setattr__(
            self,
            "graph_version",
            exact_reference(self.graph_version, "graph_version"),
        )
        object.__setattr__(
            self,
            "parent_checkpoint_ref",
            reference(self.parent_checkpoint_ref, "parent_checkpoint_ref"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "tenant_scope_ref": self.tenant_scope_ref,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "parent_checkpoint_ref": self.parent_checkpoint_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "tenant_id",
                        "tenant_scope_ref",
                        "run_id",
                        "graph_id",
                        "graph_version",
                        "node_id",
                        "attempt_id",
                        "parent_checkpoint_ref",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class BoundedSummary:
    text: str
    byte_size: int
    token_estimate: int
    complete: bool = True

    def __post_init__(self) -> None:
        text = required_text(self.text, "summary.text", max_length=1_048_576)
        actual_bytes = len(text.encode("utf-8"))
        actual_tokens = estimated_tokens(actual_bytes)
        if self.byte_size != actual_bytes or self.token_estimate != actual_tokens:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="summary",
            )
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "summary.byte_size"))
        object.__setattr__(
            self,
            "token_estimate",
            non_negative_int(self.token_estimate, "summary.token_estimate"),
        )
        object.__setattr__(self, "complete", boolean(self.complete, "summary.complete"))

    @classmethod
    def from_text(cls, text: str, *, complete: bool = True) -> Self:
        normalized = required_text(text, "summary.text", max_length=1_048_576)
        byte_size = len(normalized.encode("utf-8"))
        return cls(
            text=normalized,
            byte_size=byte_size,
            token_estimate=estimated_tokens(byte_size),
            complete=complete,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "byte_size": self.byte_size,
            "token_estimate": self.token_estimate,
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset({"text", "byte_size", "token_estimate", "complete"}),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ResultProvenance:
    producer_ref: str
    producer_revision: str
    source_refs: tuple[str, ...] = ()
    parent_result_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "producer_ref",
            exact_reference(self.producer_ref, "provenance.producer_ref"),
        )
        object.__setattr__(
            self,
            "producer_revision",
            exact_reference(self.producer_revision, "provenance.producer_revision"),
        )
        for field_name in ("source_refs", "parent_result_refs"):
            object.__setattr__(
                self,
                field_name,
                stable_tuple(
                    getattr(self, field_name),
                    f"provenance.{field_name}",
                    normalize=reference,
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer_ref": self.producer_ref,
            "producer_revision": self.producer_revision,
            "source_refs": list(self.source_refs),
            "parent_result_refs": list(self.parent_result_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "producer_ref",
                    "producer_revision",
                    "source_refs",
                    "parent_result_refs",
                }
            ),
            model=cls.__name__,
        )
        return cls(
            producer_ref=payload["producer_ref"],
            producer_revision=payload["producer_revision"],
            source_refs=tuple(payload["source_refs"]),
            parent_result_refs=tuple(payload["parent_result_refs"]),
        )


@dataclass(frozen=True, slots=True)
class ResultMetrics:
    candidate_bytes: int
    candidate_tokens: int
    summary_bytes: int
    inline_bytes: int

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_bytes",
            "candidate_tokens",
            "summary_bytes",
            "inline_bytes",
        ):
            object.__setattr__(
                self,
                field_name,
                non_negative_int(getattr(self, field_name), f"metrics.{field_name}"),
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "candidate_bytes": self.candidate_bytes,
            "candidate_tokens": self.candidate_tokens,
            "summary_bytes": self.summary_bytes,
            "inline_bytes": self.inline_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "candidate_bytes",
                        "candidate_tokens",
                        "summary_bytes",
                        "inline_bytes",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    ref: str
    artifact_id: str
    artifact_type: str
    content_checksum: str
    byte_size: int
    media_type: str
    artifact_class: ArtifactClass
    tenant_id: str
    run_id: str
    graph_id: str
    node_id: str
    attempt_id: str
    producer_revision: str
    sensitivity: ResultSensitivity
    reusable: bool
    dependency_digest: str | None
    retention_class: RetentionClass
    expires_at: datetime | None
    required_for_replay: bool
    required_for_publication: bool
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", reference(self.ref, "artifact.ref"))
        for field_name in (
            "artifact_id",
            "artifact_type",
            "tenant_id",
            "run_id",
            "graph_id",
            "node_id",
            "attempt_id",
        ):
            object.__setattr__(self, field_name, identifier(getattr(self, field_name), f"artifact.{field_name}"))
        object.__setattr__(
            self,
            "content_checksum",
            checksum(self.content_checksum, "artifact.content_checksum"),
        )
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "artifact.byte_size"))
        object.__setattr__(self, "media_type", media_type(self.media_type, "artifact.media_type"))
        object.__setattr__(
            self,
            "artifact_class",
            enum_value(ArtifactClass, self.artifact_class, "artifact.artifact_class"),
        )
        object.__setattr__(
            self,
            "producer_revision",
            exact_reference(self.producer_revision, "artifact.producer_revision"),
        )
        object.__setattr__(
            self,
            "sensitivity",
            enum_value(ResultSensitivity, self.sensitivity, "artifact.sensitivity"),
        )
        object.__setattr__(self, "reusable", boolean(self.reusable, "artifact.reusable"))
        dependency = self.dependency_digest
        if dependency is not None:
            dependency = checksum(dependency, "artifact.dependency_digest")
        if self.reusable and dependency is None:
            raise result_error(
                GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID,
                field="artifact.dependency_digest",
            )
        object.__setattr__(self, "dependency_digest", dependency)
        object.__setattr__(
            self,
            "retention_class",
            enum_value(RetentionClass, self.retention_class, "artifact.retention_class"),
        )
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", aware_datetime(self.expires_at, "artifact.expires_at"))
        for field_name in ("required_for_replay", "required_for_publication"):
            object.__setattr__(self, field_name, boolean(getattr(self, field_name), f"artifact.{field_name}"))
        created_at = aware_datetime(self.created_at, "artifact.created_at")
        object.__setattr__(self, "created_at", created_at)
        if self.expires_at is not None and self.expires_at <= created_at:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="artifact.expires_at",
            )

    def scope(self) -> tuple[str, str, str, str, str]:
        return (self.tenant_id, self.run_id, self.graph_id, self.node_id, self.attempt_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "content_checksum": self.content_checksum,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "artifact_class": self.artifact_class.value,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "producer_revision": self.producer_revision,
            "sensitivity": self.sensitivity.value,
            "reusable": self.reusable,
            "dependency_digest": self.dependency_digest,
            "retention_class": self.retention_class.value,
            "expires_at": datetime_to_json(self.expires_at) if self.expires_at is not None else None,
            "required_for_replay": self.required_for_replay,
            "required_for_publication": self.required_for_publication,
            "created_at": datetime_to_json(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(value, required=frozenset(_ARTIFACT_FIELDS), model=cls.__name__)
        payload["expires_at"] = (
            datetime_from_json(payload["expires_at"], "artifact.expires_at")
            if payload["expires_at"] is not None
            else None
        )
        payload["created_at"] = datetime_from_json(payload["created_at"], "artifact.created_at")
        return cls(**payload)


_ARTIFACT_FIELDS = (
    "ref",
    "artifact_id",
    "artifact_type",
    "content_checksum",
    "byte_size",
    "media_type",
    "artifact_class",
    "tenant_id",
    "run_id",
    "graph_id",
    "node_id",
    "attempt_id",
    "producer_revision",
    "sensitivity",
    "reusable",
    "dependency_digest",
    "retention_class",
    "expires_at",
    "required_for_replay",
    "required_for_publication",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class CacheRef:
    ref: str
    tenant_id: str
    content_checksum: str
    dependency_digest: str
    media_type: str
    byte_size: int
    policy_version: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", reference(self.ref, "cache.ref"))
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "cache.tenant_id"))
        object.__setattr__(self, "content_checksum", checksum(self.content_checksum, "cache.content_checksum"))
        object.__setattr__(self, "dependency_digest", checksum(self.dependency_digest, "cache.dependency_digest"))
        object.__setattr__(self, "media_type", media_type(self.media_type, "cache.media_type"))
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "cache.byte_size"))
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "cache.policy_version"))
        object.__setattr__(self, "expires_at", aware_datetime(self.expires_at, "cache.expires_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "tenant_id": self.tenant_id,
            "content_checksum": self.content_checksum,
            "dependency_digest": self.dependency_digest,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "policy_version": self.policy_version,
            "expires_at": datetime_to_json(self.expires_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "ref",
                    "tenant_id",
                    "content_checksum",
                    "dependency_digest",
                    "media_type",
                    "byte_size",
                    "policy_version",
                    "expires_at",
                }
            ),
            model=cls.__name__,
        )
        payload["expires_at"] = datetime_from_json(payload["expires_at"], "cache.expires_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class PersistenceDecision:
    mode: PersistenceMode
    reason: PersistenceReason
    artifact_class: ArtifactClass
    retention_class: RetentionClass
    estimated_bytes: int
    reserved_bytes: int
    context_policy: ContextPolicy
    required: bool
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", enum_value(PersistenceMode, self.mode, "decision.mode"))
        object.__setattr__(self, "reason", enum_value(PersistenceReason, self.reason, "decision.reason"))
        object.__setattr__(self, "artifact_class", enum_value(ArtifactClass, self.artifact_class, "decision.artifact_class"))
        object.__setattr__(self, "retention_class", enum_value(RetentionClass, self.retention_class, "decision.retention_class"))
        object.__setattr__(self, "estimated_bytes", non_negative_int(self.estimated_bytes, "decision.estimated_bytes"))
        object.__setattr__(self, "reserved_bytes", non_negative_int(self.reserved_bytes, "decision.reserved_bytes"))
        object.__setattr__(self, "context_policy", enum_value(ContextPolicy, self.context_policy, "decision.context_policy"))
        object.__setattr__(self, "required", boolean(self.required, "decision.required"))
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "decision.policy_version"))
        if self.mode in {PersistenceMode.INLINE, PersistenceMode.OMITTED} and self.reserved_bytes != 0:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="decision.reserved_bytes")
        if self.mode in {PersistenceMode.ARTIFACT, PersistenceMode.CACHE} and self.reserved_bytes != self.estimated_bytes:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="decision.reserved_bytes")
        if self.mode is PersistenceMode.OMITTED and self.required:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="decision.required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "reason": self.reason.value,
            "artifact_class": self.artifact_class.value,
            "retention_class": self.retention_class.value,
            "estimated_bytes": self.estimated_bytes,
            "reserved_bytes": self.reserved_bytes,
            "context_policy": self.context_policy.value,
            "required": self.required,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "mode",
                        "reason",
                        "artifact_class",
                        "retention_class",
                        "estimated_bytes",
                        "reserved_bytes",
                        "context_policy",
                        "required",
                        "policy_version",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ContextAssemblyRequest:
    tenant_id: str
    run_id: str
    graph_id: str
    node_id: str
    purpose: ContextPurpose
    allowed_artifact_classes: tuple[ArtifactClass, ...]
    allowed_sensitivities: tuple[ResultSensitivity, ...]
    artifact_refs: tuple[str, ...]
    max_refs: int
    max_bytes: int
    max_tokens: int
    load_mode: ContextLoadMode

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "run_id", "graph_id", "node_id"):
            object.__setattr__(self, field_name, identifier(getattr(self, field_name), f"context.{field_name}"))
        if isinstance(self.allowed_artifact_classes, str) or not isinstance(self.allowed_artifact_classes, Sequence):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="context.allowed_artifact_classes")
        classes = tuple(
            sorted(
                (enum_value(ArtifactClass, item, "context.allowed_artifact_classes") for item in self.allowed_artifact_classes),
                key=lambda item: item.value,
            )
        )
        if not classes or len(classes) != len(set(classes)):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="context.allowed_artifact_classes")
        object.__setattr__(self, "allowed_artifact_classes", classes)
        if isinstance(self.allowed_sensitivities, str) or not isinstance(
            self.allowed_sensitivities,
            Sequence,
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context.allowed_sensitivities",
            )
        sensitivities = tuple(
            sorted(
                (
                    enum_value(
                        ResultSensitivity,
                        item,
                        "context.allowed_sensitivities",
                    )
                    for item in self.allowed_sensitivities
                ),
                key=lambda item: item.value,
            )
        )
        if not sensitivities or len(sensitivities) != len(set(sensitivities)):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context.allowed_sensitivities",
            )
        object.__setattr__(self, "allowed_sensitivities", sensitivities)
        object.__setattr__(
            self,
            "purpose",
            enum_value(ContextPurpose, self.purpose, "context.purpose"),
        )
        if isinstance(self.artifact_refs, (str, bytes, bytearray)) or not isinstance(
            self.artifact_refs,
            Sequence,
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context.artifact_refs",
            )
        refs = tuple(
            sorted(
                {
                    reference(item, "context.artifact_refs")
                    for item in self.artifact_refs
                }
            )
        )
        object.__setattr__(self, "artifact_refs", refs)
        for field_name in ("max_refs", "max_bytes", "max_tokens"):
            object.__setattr__(self, field_name, non_negative_int(getattr(self, field_name), f"context.{field_name}"))
        object.__setattr__(self, "load_mode", enum_value(ContextLoadMode, self.load_mode, "context.load_mode"))
        if len(refs) > self.max_refs:
            raise result_error(
                GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED,
                field="context.artifact_refs",
                actual=len(refs),
                limit=self.max_refs,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "purpose": self.purpose.value,
            "allowed_artifact_classes": [item.value for item in self.allowed_artifact_classes],
            "allowed_sensitivities": [
                item.value for item in self.allowed_sensitivities
            ],
            "artifact_refs": list(self.artifact_refs),
            "max_refs": self.max_refs,
            "max_bytes": self.max_bytes,
            "max_tokens": self.max_tokens,
            "load_mode": self.load_mode.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "tenant_id",
                    "run_id",
                    "graph_id",
                    "node_id",
                    "purpose",
                    "allowed_artifact_classes",
                    "allowed_sensitivities",
                    "artifact_refs",
                    "max_refs",
                    "max_bytes",
                    "max_tokens",
                    "load_mode",
                }
            ),
            model=cls.__name__,
        )
        payload["allowed_artifact_classes"] = tuple(payload["allowed_artifact_classes"])
        payload["allowed_sensitivities"] = tuple(payload["allowed_sensitivities"])
        payload["artifact_refs"] = tuple(payload["artifact_refs"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class NodeResultEnvelope:
    binding: NodeResultBinding
    status: NodeResultStatus
    output_schema_ref: str
    output_schema_digest: str
    candidate_checksum: str
    summary: BoundedSummary
    inline_projection: Mapping[str, Any]
    materialized_refs: tuple[ArtifactRecord, ...]
    cache_refs: tuple[CacheRef, ...]
    provenance: ResultProvenance
    persistence_decision: PersistenceDecision
    metrics: ResultMetrics
    created_at: datetime
    envelope_schema: str = "newsroom.graph-node-result@1"

    def __post_init__(self) -> None:
        if not isinstance(self.binding, NodeResultBinding):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="binding")
        object.__setattr__(self, "status", enum_value(NodeResultStatus, self.status, "status"))
        object.__setattr__(self, "output_schema_ref", exact_reference(self.output_schema_ref, "output_schema_ref"))
        object.__setattr__(self, "output_schema_digest", checksum(self.output_schema_digest, "output_schema_digest"))
        object.__setattr__(self, "candidate_checksum", checksum(self.candidate_checksum, "candidate_checksum"))
        if not isinstance(self.summary, BoundedSummary):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="summary")
        projection = canonical_mapping(
            self.inline_projection,
            "inline_projection",
            max_depth=8,
            max_keys=256,
            max_bytes=1_048_576,
        )
        object.__setattr__(self, "inline_projection", projection)
        records = tuple(self.materialized_refs)
        caches = tuple(self.cache_refs)
        if any(not isinstance(item, ArtifactRecord) for item in records):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="materialized_refs")
        if any(not isinstance(item, CacheRef) for item in caches):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="cache_refs")
        if len({item.ref for item in records}) != len(records) or len({item.ref for item in caches}) != len(caches):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="result_refs")
        object.__setattr__(self, "materialized_refs", tuple(sorted(records, key=lambda item: item.ref)))
        object.__setattr__(self, "cache_refs", tuple(sorted(caches, key=lambda item: item.ref)))
        if not isinstance(self.provenance, ResultProvenance):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="provenance")
        if not isinstance(self.persistence_decision, PersistenceDecision):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="persistence_decision")
        if not isinstance(self.metrics, ResultMetrics):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="metrics")
        object.__setattr__(self, "created_at", aware_datetime(self.created_at, "created_at"))
        object.__setattr__(self, "envelope_schema", exact_reference(self.envelope_schema, "envelope_schema"))
        self._validate_cross_fields()

    @property
    def run_id(self) -> str:
        return self.binding.run_id

    @property
    def graph_id(self) -> str:
        return self.binding.graph_id

    @property
    def node_id(self) -> str:
        return self.binding.node_id

    @property
    def attempt_id(self) -> str:
        return self.binding.attempt_id

    def _validate_cross_fields(self) -> None:
        expected_scope = (
            self.binding.tenant_id,
            self.binding.run_id,
            self.binding.graph_id,
            self.binding.node_id,
            self.binding.attempt_id,
        )
        if any(record.scope() != expected_scope for record in self.materialized_refs):
            raise result_error(GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH, field="materialized_refs")
        if any(cache.tenant_id != self.binding.tenant_id for cache in self.cache_refs):
            raise result_error(GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH, field="cache_refs")
        if any(record.content_checksum != self.candidate_checksum for record in self.materialized_refs):
            raise result_error(GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH, field="candidate_checksum")
        if any(cache.content_checksum != self.candidate_checksum for cache in self.cache_refs):
            raise result_error(GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID, field="candidate_checksum")
        mode = self.persistence_decision.mode
        if mode is PersistenceMode.INLINE and (self.materialized_refs or self.cache_refs):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="result_refs")
        if mode is PersistenceMode.ARTIFACT and not self.materialized_refs:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="materialized_refs")
        if mode is PersistenceMode.CACHE and not self.cache_refs:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="cache_refs")
        if mode is PersistenceMode.OMITTED and (self.inline_projection or self.materialized_refs or self.cache_refs):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="omitted_result")
        if self.metrics.candidate_bytes != self.persistence_decision.estimated_bytes:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="metrics.candidate_bytes")
        if self.metrics.summary_bytes != self.summary.byte_size:
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field="metrics.summary_bytes")
        expected_inline_bytes = (
            len(canonical_json_bytes(self.inline_projection))
            if mode is PersistenceMode.INLINE
            or (
                mode in {PersistenceMode.ARTIFACT, PersistenceMode.CACHE}
                and bool(self.inline_projection)
            )
            else 0
        )
        if self.metrics.inline_bytes != expected_inline_bytes:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="metrics.inline_bytes",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_schema": self.envelope_schema,
            "binding": self.binding.to_dict(),
            "status": self.status.value,
            "output_schema_ref": self.output_schema_ref,
            "output_schema_digest": self.output_schema_digest,
            "candidate_checksum": self.candidate_checksum,
            "summary": self.summary.to_dict(),
            "inline_projection": thaw_mapping(self.inline_projection),
            "materialized_refs": [item.to_dict() for item in self.materialized_refs],
            "cache_refs": [item.to_dict() for item in self.cache_refs],
            "provenance": self.provenance.to_dict(),
            "persistence_decision": self.persistence_decision.to_dict(),
            "metrics": self.metrics.to_dict(),
            "created_at": datetime_to_json(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "envelope_schema",
                    "binding",
                    "status",
                    "output_schema_ref",
                    "output_schema_digest",
                    "candidate_checksum",
                    "summary",
                    "inline_projection",
                    "materialized_refs",
                    "cache_refs",
                    "provenance",
                    "persistence_decision",
                    "metrics",
                    "created_at",
                }
            ),
            model=cls.__name__,
        )
        return cls(
            envelope_schema=payload["envelope_schema"],
            binding=NodeResultBinding.from_dict(payload["binding"]),
            status=payload["status"],
            output_schema_ref=payload["output_schema_ref"],
            output_schema_digest=payload["output_schema_digest"],
            candidate_checksum=payload["candidate_checksum"],
            summary=BoundedSummary.from_dict(payload["summary"]),
            inline_projection=payload["inline_projection"],
            materialized_refs=tuple(ArtifactRecord.from_dict(item) for item in payload["materialized_refs"]),
            cache_refs=tuple(CacheRef.from_dict(item) for item in payload["cache_refs"]),
            provenance=ResultProvenance.from_dict(payload["provenance"]),
            persistence_decision=PersistenceDecision.from_dict(payload["persistence_decision"]),
            metrics=ResultMetrics.from_dict(payload["metrics"]),
            created_at=datetime_from_json(payload["created_at"], "created_at"),
        )


__all__ = [
    "ArtifactClass",
    "ArtifactRecord",
    "BoundedSummary",
    "CacheRef",
    "ContextAssemblyRequest",
    "ContextLoadMode",
    "ContextPolicy",
    "ContextPurpose",
    "NodeResultBinding",
    "NodeResultEnvelope",
    "NodeResultStatus",
    "PersistenceDecision",
    "PersistenceMode",
    "PersistenceReason",
    "ResultMetrics",
    "ResultProvenance",
    "ResultSensitivity",
    "RetentionClass",
]
