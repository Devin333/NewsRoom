from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from framework.events.canonical import canonical_json_bytes
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.canonical import (
    canonical_checksum,
    exact_reference,
    freeze_json,
    required_text,
    thaw_json,
)


HARNESS_GRAPH_RESULT_LINEAGE_SCHEMA = "newsroom.harness-graph-result-lineage@1"
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,511}\Z")
_REFERENCE = re.compile(
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s]{1,2040}\Z|"
    r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,2047}\Z"
)
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)
_MAX_INLINE_BYTES = 32 * 1024
_MAX_INLINE_DEPTH = 8
_MAX_INLINE_KEYS = 256
_MAX_SUMMARY_BYTES = 8 * 1024
_MAX_SUMMARY_TOKENS = 2_048
_MAX_REFS = 64
_MAX_LINEAGE_BYTES = 48 * 1024
_RESERVED_INLINE_FIELDS = frozenset(
    {
        "candidate",
        "gate_decision",
        "materialized_refs",
        "memory_write",
        "persistence_decision",
        "publication",
        "raw_prompt",
        "route",
        "routing",
        "tool_authorization",
    }
)
_SENSITIVE_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "hidden_prompt",
        "password",
        "private_context",
        "raw_prompt",
        "refresh_token",
        "secret",
        "system_prompt",
    }
)


class HarnessGraphResultLineageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    HALTED = "halted"


class HarnessGraphResultPersistenceMode(StrEnum):
    INLINE = "inline"
    ARTIFACT = "artifact"
    CACHE = "cache"
    OMITTED = "omitted"


@dataclass(frozen=True, slots=True)
class HarnessGraphResultSummary:
    text: str
    byte_size: int
    token_estimate: int
    complete: bool

    def __post_init__(self) -> None:
        text = required_text(self.text, "result_lineage.summary.text")
        byte_size = _nonnegative_int(self.byte_size, "result_lineage.summary.byte_size")
        token_estimate = _nonnegative_int(
            self.token_estimate,
            "result_lineage.summary.token_estimate",
        )
        if (
            byte_size != len(text.encode("utf-8"))
            or byte_size > _MAX_SUMMARY_BYTES
            or token_estimate != (0 if byte_size == 0 else (byte_size + 3) // 4)
            or token_estimate > _MAX_SUMMARY_TOKENS
        ):
            raise HarnessValidationError(
                "graph result summary exceeds or conflicts with its bounds",
                code="graph_result_lineage_summary_invalid",
            )
        if not isinstance(self.complete, bool):
            raise HarnessValidationError(
                "graph result summary complete flag must be boolean",
                code="graph_result_lineage_summary_invalid",
            )
        object.__setattr__(self, "text", text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "byte_size": self.byte_size,
            "token_estimate": self.token_estimate,
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        _exact_keys(value, {"text", "byte_size", "token_estimate", "complete"}, "summary")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class HarnessGraphArtifactRefProjection:
    ref: str
    artifact_id: str
    artifact_type: str
    content_checksum: str
    byte_size: int
    media_type: str
    artifact_class: str
    retention_class: str
    tenant_id: str
    run_id: str
    graph_id: str
    node_id: str
    attempt_id: str
    required_for_replay: bool
    required_for_publication: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", _reference(self.ref, "artifact.ref"))
        for field_name in ("artifact_id", "artifact_type"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), f"artifact.{field_name}"))
        object.__setattr__(self, "content_checksum", _checksum(self.content_checksum, "artifact.content_checksum"))
        object.__setattr__(self, "byte_size", _nonnegative_int(self.byte_size, "artifact.byte_size"))
        object.__setattr__(self, "media_type", _media_type(self.media_type, "artifact.media_type"))
        object.__setattr__(self, "artifact_class", required_text(self.artifact_class, "artifact.artifact_class"))
        object.__setattr__(self, "retention_class", required_text(self.retention_class, "artifact.retention_class"))
        for field_name in ("tenant_id", "run_id", "graph_id", "node_id", "attempt_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), f"artifact.{field_name}"))
        for field_name in ("required_for_replay", "required_for_publication"):
            if not isinstance(getattr(self, field_name), bool):
                raise HarnessValidationError(
                    "graph artifact ref required flags must be boolean",
                    code="graph_result_lineage_ref_invalid",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "content_checksum": self.content_checksum,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "artifact_class": self.artifact_class,
            "retention_class": self.retention_class,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "required_for_replay": self.required_for_replay,
            "required_for_publication": self.required_for_publication,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected = {
            "ref",
            "artifact_id",
            "artifact_type",
            "content_checksum",
            "byte_size",
            "media_type",
            "artifact_class",
            "retention_class",
            "tenant_id",
            "run_id",
            "graph_id",
            "node_id",
            "attempt_id",
            "required_for_replay",
            "required_for_publication",
        }
        _exact_keys(value, expected, "artifact ref")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class HarnessGraphCacheRefProjection:
    ref: str
    tenant_id: str
    content_checksum: str
    dependency_digest: str
    media_type: str
    byte_size: int
    policy_version: str
    expires_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", _reference(self.ref, "cache.ref"))
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "cache.tenant_id"))
        object.__setattr__(self, "content_checksum", _checksum(self.content_checksum, "cache.content_checksum"))
        object.__setattr__(self, "dependency_digest", _checksum(self.dependency_digest, "cache.dependency_digest"))
        object.__setattr__(self, "media_type", _media_type(self.media_type, "cache.media_type"))
        object.__setattr__(self, "byte_size", _nonnegative_int(self.byte_size, "cache.byte_size"))
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "cache.policy_version"))
        object.__setattr__(self, "expires_at", required_text(self.expires_at, "cache.expires_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "tenant_id": self.tenant_id,
            "content_checksum": self.content_checksum,
            "dependency_digest": self.dependency_digest,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "policy_version": self.policy_version,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected = {
            "ref",
            "tenant_id",
            "content_checksum",
            "dependency_digest",
            "media_type",
            "byte_size",
            "policy_version",
            "expires_at",
        }
        _exact_keys(value, expected, "cache ref")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class HarnessGraphResultLineage:
    tenant_id: str
    run_id: str
    graph_id: str
    graph_version: str
    node_id: str
    node_instance_id: str
    attempt_id: str
    attempt: int
    parent_checkpoint_ref: str
    status: HarnessGraphResultLineageStatus | str
    output_schema_ref: str
    output_schema_digest: str
    candidate_checksum: str
    envelope_checksum: str
    candidate_bytes: int
    candidate_tokens: int
    summary: HarnessGraphResultSummary
    inline_projection: Mapping[str, Any]
    artifact_refs: tuple[HarnessGraphArtifactRefProjection, ...] = ()
    cache_refs: tuple[HarnessGraphCacheRefProjection, ...] = ()
    persistence_mode: HarnessGraphResultPersistenceMode | str = HarnessGraphResultPersistenceMode.INLINE
    policy_version: str = "graph-artifact-policy@1"
    required: bool = False
    tenant_scope_ref: str | None = None
    identity_scope_ref: str | None = None
    subject_scope_ref: str | None = None
    context_fingerprint: str | None = None
    producer_ref: str = "unknown@1"
    producer_revision: str = "unknown@1"
    source_refs: tuple[str, ...] = ()
    parent_result_refs: tuple[str, ...] = ()
    inline_bytes: int = 0
    schema_version: str = HARNESS_GRAPH_RESULT_LINEAGE_SCHEMA
    lineage_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "run_id",
            "graph_id",
            "node_id",
            "node_instance_id",
            "attempt_id",
        ):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), f"lineage.{field_name}"))
        object.__setattr__(self, "graph_version", exact_reference(self.graph_version, "lineage.graph_version"))
        object.__setattr__(self, "attempt", _positive_int(self.attempt, "lineage.attempt"))
        object.__setattr__(self, "parent_checkpoint_ref", _reference(self.parent_checkpoint_ref, "lineage.parent_checkpoint_ref"))
        object.__setattr__(self, "status", HarnessGraphResultLineageStatus(self.status))
        object.__setattr__(self, "output_schema_ref", exact_reference(self.output_schema_ref, "lineage.output_schema_ref"))
        object.__setattr__(self, "output_schema_digest", _checksum(self.output_schema_digest, "lineage.output_schema_digest"))
        object.__setattr__(self, "candidate_checksum", _checksum(self.candidate_checksum, "lineage.candidate_checksum"))
        object.__setattr__(self, "envelope_checksum", _checksum(self.envelope_checksum, "lineage.envelope_checksum"))
        object.__setattr__(self, "candidate_bytes", _nonnegative_int(self.candidate_bytes, "lineage.candidate_bytes"))
        object.__setattr__(self, "candidate_tokens", _nonnegative_int(self.candidate_tokens, "lineage.candidate_tokens"))
        object.__setattr__(self, "inline_bytes", _nonnegative_int(self.inline_bytes, "lineage.inline_bytes"))
        if not isinstance(self.summary, HarnessGraphResultSummary):
            raise TypeError("summary must be HarnessGraphResultSummary")
        projection = _bounded_inline_projection(self.inline_projection)
        object.__setattr__(self, "inline_projection", projection)
        mode = HarnessGraphResultPersistenceMode(self.persistence_mode)
        object.__setattr__(self, "persistence_mode", mode)
        expected_inline_bytes = (
            len(canonical_json_bytes(projection))
            if mode is HarnessGraphResultPersistenceMode.INLINE
            or (
                mode
                in {
                    HarnessGraphResultPersistenceMode.ARTIFACT,
                    HarnessGraphResultPersistenceMode.CACHE,
                }
                and bool(projection)
            )
            else 0
        )
        if self.inline_bytes != expected_inline_bytes:
            raise HarnessValidationError(
                "graph result inline byte size does not match its projection",
                code="graph_result_lineage_projection_invalid",
            )
        artifacts = tuple(self.artifact_refs)
        caches = tuple(self.cache_refs)
        if (
            len(artifacts) > _MAX_REFS
            or len(caches) > _MAX_REFS
            or not all(isinstance(item, HarnessGraphArtifactRefProjection) for item in artifacts)
            or not all(isinstance(item, HarnessGraphCacheRefProjection) for item in caches)
            or len({item.ref for item in artifacts}) != len(artifacts)
            or len({item.ref for item in caches}) != len(caches)
        ):
            raise HarnessValidationError(
                "graph result refs violate their bound or identity",
                code="graph_result_lineage_ref_invalid",
            )
        object.__setattr__(self, "artifact_refs", tuple(sorted(artifacts, key=lambda item: item.ref)))
        object.__setattr__(self, "cache_refs", tuple(sorted(caches, key=lambda item: item.ref)))
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "lineage.policy_version"))
        if not isinstance(self.required, bool):
            raise HarnessValidationError(
                "graph result lineage required flag must be boolean",
                code="graph_result_lineage_invalid",
            )
        for field_name in (
            "tenant_scope_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _checksum(value, f"lineage.{field_name}"),
                )
        if self.context_fingerprint is not None:
            object.__setattr__(self, "context_fingerprint", _checksum(self.context_fingerprint, "lineage.context_fingerprint"))
        object.__setattr__(self, "producer_ref", exact_reference(self.producer_ref, "lineage.producer_ref"))
        object.__setattr__(self, "producer_revision", exact_reference(self.producer_revision, "lineage.producer_revision"))
        object.__setattr__(self, "source_refs", _bounded_refs(self.source_refs, "lineage.source_refs"))
        object.__setattr__(self, "parent_result_refs", _bounded_refs(self.parent_result_refs, "lineage.parent_result_refs"))
        if self.schema_version != HARNESS_GRAPH_RESULT_LINEAGE_SCHEMA:
            raise HarnessValidationError(
                "unsupported graph result lineage schema",
                code="unsupported_graph_result_lineage_schema",
            )
        self._validate_mode()
        checksum_projection = self.checksum_projection()
        if len(canonical_json_bytes(checksum_projection)) > _MAX_LINEAGE_BYTES:
            raise HarnessValidationError(
                "graph result lineage exceeds its durable event bound",
                code="graph_result_lineage_too_large",
            )
        object.__setattr__(self, "lineage_checksum", canonical_checksum(checksum_projection))

    def _validate_mode(self) -> None:
        has_inline = bool(self.inline_projection)
        if self.persistence_mode is HarnessGraphResultPersistenceMode.INLINE:
            valid = not self.artifact_refs and not self.cache_refs
        elif self.persistence_mode is HarnessGraphResultPersistenceMode.ARTIFACT:
            valid = bool(self.artifact_refs) and not self.cache_refs
        elif self.persistence_mode is HarnessGraphResultPersistenceMode.CACHE:
            valid = bool(self.cache_refs) and not self.artifact_refs
        else:
            valid = not has_inline and not self.artifact_refs and not self.cache_refs and not self.required
        if not valid:
            raise HarnessValidationError(
                "graph result persistence mode conflicts with its projected values",
                code="graph_result_lineage_mode_mismatch",
            )
        if any(item.content_checksum != self.candidate_checksum for item in (*self.artifact_refs, *self.cache_refs)):
            raise HarnessValidationError(
                "graph result refs do not match the candidate checksum",
                code="graph_result_lineage_checksum_mismatch",
            )
        expected_scope = (
            self.tenant_id,
            self.run_id,
            self.graph_id,
            self.node_id,
            self.attempt_id,
        )
        if any(
            (
                item.tenant_id,
                item.run_id,
                item.graph_id,
                item.node_id,
                item.attempt_id,
            )
            != expected_scope
            for item in self.artifact_refs
        ) or any(item.tenant_id != self.tenant_id for item in self.cache_refs):
            raise HarnessValidationError(
                "graph result refs are outside the result scope",
                code="graph_result_lineage_scope_mismatch",
            )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "attempt_id": self.attempt_id,
            "attempt": self.attempt,
            "parent_checkpoint_ref": self.parent_checkpoint_ref,
            "status": self.status.value,
            "output_schema_ref": self.output_schema_ref,
            "output_schema_digest": self.output_schema_digest,
            "candidate_checksum": self.candidate_checksum,
            "envelope_checksum": self.envelope_checksum,
            "candidate_bytes": self.candidate_bytes,
            "candidate_tokens": self.candidate_tokens,
            "summary": self.summary.to_dict(),
            "inline_projection": thaw_json(self.inline_projection),
            "artifact_refs": [item.to_dict() for item in self.artifact_refs],
            "cache_refs": [item.to_dict() for item in self.cache_refs],
            "persistence_mode": self.persistence_mode.value,
            "policy_version": self.policy_version,
            "required": self.required,
            "tenant_scope_ref": self.tenant_scope_ref,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "context_fingerprint": self.context_fingerprint,
            "producer_ref": self.producer_ref,
            "producer_revision": self.producer_revision,
            "source_refs": list(self.source_refs),
            "parent_result_refs": list(self.parent_result_refs),
            "inline_bytes": self.inline_bytes,
        }

    def control_projection(self) -> dict[str, Any]:
        """Return the bounded result facts permitted in GraphState."""

        return {
            "schema_version": self.schema_version,
            "lineage_checksum": self.lineage_checksum,
            "node_instance_id": self.node_instance_id,
            "attempt_id": self.attempt_id,
            "attempt": self.attempt,
            "parent_checkpoint_ref": self.parent_checkpoint_ref,
            "status": self.status.value,
            "output_schema_ref": self.output_schema_ref,
            "output_schema_digest": self.output_schema_digest,
            "candidate_checksum": self.candidate_checksum,
            "envelope_checksum": self.envelope_checksum,
            "candidate_bytes": self.candidate_bytes,
            "candidate_tokens": self.candidate_tokens,
            "summary": self.summary.to_dict(),
            "inline_projection": thaw_json(self.inline_projection),
            "artifact_refs": [item.to_dict() for item in self.artifact_refs],
            "cache_refs": [item.to_dict() for item in self.cache_refs],
            "persistence_mode": self.persistence_mode.value,
            "policy_version": self.policy_version,
            "required": self.required,
            "context_fingerprint": self.context_fingerprint,
            "source_refs": list(self.source_refs),
            "parent_result_refs": list(self.parent_result_refs),
            "inline_bytes": self.inline_bytes,
        }

    def reference_projection(self) -> dict[str, Any]:
        """Return compact attempt history for retries and compensation."""

        return {
            "lineage_checksum": self.lineage_checksum,
            "attempt_id": self.attempt_id,
            "attempt": self.attempt,
            "status": self.status.value,
            "candidate_checksum": self.candidate_checksum,
            "envelope_checksum": self.envelope_checksum,
            "artifact_refs": [item.ref for item in self.artifact_refs],
            "cache_refs": [item.ref for item in self.cache_refs],
            "policy_version": self.policy_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "lineage_checksum": self.lineage_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected = {
            "schema_version", "tenant_id", "run_id", "graph_id", "graph_version",
            "node_id", "node_instance_id", "attempt_id", "attempt",
            "parent_checkpoint_ref", "status", "output_schema_ref",
            "output_schema_digest", "candidate_checksum", "envelope_checksum",
            "candidate_bytes", "candidate_tokens", "summary", "inline_projection",
            "artifact_refs", "cache_refs", "persistence_mode", "policy_version",
            "required", "tenant_scope_ref", "identity_scope_ref",
            "subject_scope_ref", "context_fingerprint", "producer_ref", "producer_revision",
            "source_refs", "parent_result_refs", "inline_bytes", "lineage_checksum",
        }
        _exact_keys(value, expected, "graph result lineage")
        payload = dict(value)
        payload["summary"] = HarnessGraphResultSummary.from_dict(_mapping(payload["summary"], "summary"))
        payload["artifact_refs"] = tuple(
            HarnessGraphArtifactRefProjection.from_dict(_mapping(item, "artifact ref"))
            for item in _sequence(payload["artifact_refs"], "artifact refs")
        )
        payload["cache_refs"] = tuple(
            HarnessGraphCacheRefProjection.from_dict(_mapping(item, "cache ref"))
            for item in _sequence(payload["cache_refs"], "cache refs")
        )
        payload["source_refs"] = tuple(_sequence(payload["source_refs"], "source refs"))
        payload["parent_result_refs"] = tuple(_sequence(payload["parent_result_refs"], "parent result refs"))
        checksum_value = payload.pop("lineage_checksum")
        result = cls(**payload)
        if checksum_value != result.lineage_checksum:
            raise HarnessValidationError(
                "graph result lineage checksum is invalid",
                code="graph_result_lineage_checksum_mismatch",
            )
        return result


def _bounded_inline_projection(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise HarnessValidationError(
            "graph result inline projection must be an object",
            code="graph_result_lineage_projection_invalid",
        )
    _reject_disallowed_fields(value, root=True)
    depth, key_count = _shape(value)
    if depth > _MAX_INLINE_DEPTH or key_count > _MAX_INLINE_KEYS:
        raise HarnessValidationError(
            "graph result inline projection exceeds its shape bound",
            code="graph_result_lineage_projection_invalid",
        )
    frozen = freeze_json(value, "result_lineage.inline_projection")
    if not isinstance(frozen, Mapping) or len(canonical_json_bytes(frozen)) > _MAX_INLINE_BYTES:
        raise HarnessValidationError(
            "graph result inline projection exceeds its byte bound",
            code="graph_result_lineage_projection_invalid",
        )
    return frozen


def _reject_disallowed_fields(value: Any, *, root: bool = False) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if normalized in _SENSITIVE_FIELDS or (root and normalized in _RESERVED_INLINE_FIELDS):
                raise HarnessValidationError(
                    "graph result inline projection contains a forbidden field",
                    code="graph_result_lineage_projection_invalid",
                )
            _reject_disallowed_fields(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_disallowed_fields(item)


def _shape(value: Any, depth: int = 0) -> tuple[int, int]:
    if isinstance(value, Mapping):
        maximum = depth + 1
        keys = len(value)
        for item in value.values():
            child_depth, child_keys = _shape(item, depth + 1)
            maximum = max(maximum, child_depth)
            keys += child_keys
        return maximum, keys
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        maximum = depth + 1
        keys = 0
        for item in value:
            child_depth, child_keys = _shape(item, depth + 1)
            maximum = max(maximum, child_depth)
            keys += child_keys
        return maximum, keys
    return depth, 0


def _bounded_refs(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise HarnessValidationError("graph result refs must be an array", code="graph_result_lineage_ref_invalid")
    normalized = tuple(sorted(_reference(value, field_name) for value in values))
    if len(normalized) > _MAX_REFS or len(set(normalized)) != len(normalized):
        raise HarnessValidationError("graph result refs violate their bound", code="graph_result_lineage_ref_invalid")
    return normalized


def _identifier(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    if _IDENTIFIER.fullmatch(text) is None:
        raise HarnessValidationError(f"{field_name} is invalid", code="graph_result_lineage_invalid")
    return text


def _reference(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    if _REFERENCE.fullmatch(text) is None:
        raise HarnessValidationError(f"{field_name} is invalid", code="graph_result_lineage_ref_invalid")
    return text


def _checksum(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    if _CHECKSUM.fullmatch(text) is None:
        raise HarnessValidationError(f"{field_name} is invalid", code="graph_result_lineage_checksum_mismatch")
    return text


def _media_type(value: Any, field_name: str) -> str:
    text = required_text(value, field_name).casefold()
    if _MEDIA_TYPE.fullmatch(text) is None:
        raise HarnessValidationError(f"{field_name} is invalid", code="graph_result_lineage_ref_invalid")
    return text


def _nonnegative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HarnessValidationError(f"{field_name} must be non-negative", code="graph_result_lineage_invalid")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HarnessValidationError(f"{field_name} must be positive", code="graph_result_lineage_invalid")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise HarnessValidationError(f"{field_name} fields are invalid", code="graph_result_lineage_invalid")


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{field_name} must be an object", code="graph_result_lineage_invalid")
    return value


def _sequence(value: Any, field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise HarnessValidationError(f"{field_name} must be an array", code="graph_result_lineage_invalid")
    return tuple(value)


__all__ = [
    "HARNESS_GRAPH_RESULT_LINEAGE_SCHEMA",
    "HarnessGraphArtifactRefProjection",
    "HarnessGraphCacheRefProjection",
    "HarnessGraphResultLineage",
    "HarnessGraphResultLineageStatus",
    "HarnessGraphResultPersistenceMode",
    "HarnessGraphResultSummary",
]
