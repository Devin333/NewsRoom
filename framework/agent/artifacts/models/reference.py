from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.agent.artifacts.paths import (
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.shared.graph_identity import (
    GraphExecutionIdentity,
    GraphStageIdentity,
)
from framework.shared.hashing import hash_text
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


ARTIFACT_SCOPE_GRAPH = "graph"
ARTIFACT_SCOPE_STANDALONE = "standalone"


@dataclass(frozen=True)
class ArtifactReference:
    artifact_id: str
    uri: str
    content_type: str | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    kind: str | None = None
    size_bytes: int | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_string(self.artifact_id, "artifact_id")
        _required_string(self.uri, "uri")
        if self.run_id is not None:
            validate_artifact_path_segment(self.run_id, field="run_id")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "uri": self.uri,
            "path": self.uri,
            "content_type": self.content_type,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "created_at": format_datetime(self.created_at),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactReference":
        return cls(
            artifact_id=_required_payload_string(payload, "artifact_id"),
            uri=_required_alias_string(payload, "uri", "path"),
            content_type=_optional_str(payload.get("content_type") or payload.get("media_type")),
            checksum=_optional_str(payload.get("checksum") or payload.get("content_hash")),
            metadata=dict(payload.get("metadata") or {}),
            run_id=_optional_validated_run_id(payload.get("run_id")),
            kind=_optional_str(payload.get("kind") or payload.get("artifact_type")),
            size_bytes=_optional_int(payload.get("size_bytes")),
            created_at=parse_datetime(payload.get("created_at")) or utc_now(),
        )


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    run_id: str
    artifact_type: str
    path: str
    content_type: str
    scope_kind: str = ARTIFACT_SCOPE_STANDALONE
    graph_ref: str | None = None
    graph_checksum: str | None = None
    node_id: str | None = None
    node_instance_id: str | None = None
    graph_checkpoint_ref: str | None = None
    activity_id: str | None = None
    attempt: int | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    redacted: bool = True
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    graph_id: str | None = None
    graph_version: str | None = None

    def __post_init__(self) -> None:
        _required_identity_string(self.artifact_id, "artifact_id")
        _required_string(self.artifact_type, "artifact_type")
        _required_string(self.content_type, "content_type")
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())
        object.__setattr__(self, "metadata", dict(self.metadata))
        graph_id, graph_version = _validate_artifact_scope(
            scope_kind=self.scope_kind,
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            graph_checkpoint_ref=self.graph_checkpoint_ref,
            activity_id=self.activity_id,
            attempt=self.attempt,
        )
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "graph_version", graph_version)
        validate_relative_artifact_path(self.path, field="artifact path")
        expected_path = canonical_artifact_relative_path(self)
        if self.scope_kind == ARTIFACT_SCOPE_GRAPH and self.path != expected_path:
            raise ValueError("artifact path does not match its canonical identity")

    @property
    def uri(self) -> str:
        return self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "scope_kind": self.scope_kind,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "activity_id": self.activity_id,
            "attempt": self.attempt,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "redacted": self.redacted,
            "created_at": format_datetime(self.created_at),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRef":
        expected = {
            "artifact_id",
            "run_id",
            "scope_kind",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "node_id",
            "node_instance_id",
            "graph_checkpoint_ref",
            "activity_id",
            "attempt",
            "artifact_type",
            "path",
            "content_type",
            "size_bytes",
            "checksum",
            "redacted",
            "created_at",
            "metadata",
        }
        _require_exact_payload_fields(payload, expected, "artifact reference")
        return cls(
            artifact_id=_required_payload_string(payload, "artifact_id"),
            run_id=_required_payload_string(payload, "run_id"),
            scope_kind=_required_payload_string(payload, "scope_kind"),
            graph_ref=_strict_optional_string(payload.get("graph_ref"), "graph_ref"),
            graph_checksum=_strict_optional_string(
                payload.get("graph_checksum"),
                "graph_checksum",
            ),
            node_id=_strict_optional_string(payload.get("node_id"), "node_id"),
            node_instance_id=_strict_optional_string(
                payload.get("node_instance_id"),
                "node_instance_id",
            ),
            graph_checkpoint_ref=_strict_optional_string(
                payload.get("graph_checkpoint_ref"),
                "graph_checkpoint_ref",
            ),
            activity_id=_strict_optional_string(
                payload.get("activity_id"),
                "activity_id",
            ),
            attempt=_optional_attempt(payload.get("attempt")),
            artifact_type=_required_payload_string(payload, "artifact_type"),
            path=_required_payload_string(payload, "path"),
            content_type=_required_payload_string(payload, "content_type"),
            size_bytes=_strict_optional_int(payload.get("size_bytes"), "size_bytes"),
            checksum=_strict_optional_string(payload.get("checksum"), "checksum"),
            redacted=_required_bool(payload.get("redacted"), "redacted"),
            created_at=_required_datetime(payload.get("created_at"), "created_at"),
            metadata=_required_metadata(payload.get("metadata"), "metadata"),
            graph_id=_strict_optional_string(payload.get("graph_id"), "graph_id"),
            graph_version=_strict_optional_string(
                payload.get("graph_version"),
                "graph_version",
            ),
        )


@dataclass(frozen=True)
class ArtifactWriteRequest:
    run_id: str
    artifact_type: str
    content: bytes | str
    scope_kind: str = ARTIFACT_SCOPE_STANDALONE
    content_type: str = "application/octet-stream"
    artifact_id: str | None = None
    relative_path: str | None = None
    graph_ref: str | None = None
    graph_checksum: str | None = None
    node_id: str | None = None
    node_instance_id: str | None = None
    graph_checkpoint_ref: str | None = None
    activity_id: str | None = None
    attempt: int | None = None
    redacted: bool = True
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    graph_id: str | None = None
    graph_version: str | None = None

    def __post_init__(self) -> None:
        _required_string(self.artifact_type, "artifact_type")
        if self.artifact_id is not None:
            _required_identity_string(self.artifact_id, "artifact_id")
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())
        object.__setattr__(self, "metadata", dict(self.metadata))
        graph_id, graph_version = _validate_artifact_scope(
            scope_kind=self.scope_kind,
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            graph_checkpoint_ref=self.graph_checkpoint_ref,
            activity_id=self.activity_id,
            attempt=self.attempt,
        )
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "graph_version", graph_version)

    def content_bytes(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        return self.content.encode("utf-8")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _strict_optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string or null")
    return _required_string(value, field)


def _strict_optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer or null")
    return value


def _required_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    return value


def _required_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a datetime string")
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def _required_metadata(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object")
    return dict(value)


def _validate_artifact_scope(
    *,
    scope_kind: str,
    run_id: str,
    graph_id: str | None,
    graph_version: str | None,
    graph_ref: str | None,
    graph_checksum: str | None,
    node_id: str | None,
    node_instance_id: str | None,
    graph_checkpoint_ref: str | None,
    activity_id: str | None,
    attempt: int | None,
) -> tuple[str | None, str | None]:
    graph_values = {
        "graph_id": graph_id,
        "graph_version": graph_version,
        "graph_ref": graph_ref,
        "graph_checksum": graph_checksum,
        "node_id": node_id,
        "node_instance_id": node_instance_id,
    }
    optional_graph_values = {
        "graph_checkpoint_ref": graph_checkpoint_ref,
        "activity_id": activity_id,
        "attempt": attempt,
    }
    if scope_kind == ARTIFACT_SCOPE_STANDALONE:
        if any(value is not None for value in (*graph_values.values(), *optional_graph_values.values())):
            raise ValueError("standalone artifact cannot carry Graph identity")
        validate_artifact_path_segment(run_id, field="run_id")
        return None, None
    if scope_kind != ARTIFACT_SCOPE_GRAPH:
        raise ValueError("scope_kind must be 'graph' or 'standalone'")
    if any(value is None for value in graph_values.values()):
        raise ValueError(
            "Graph artifact lineage requires run_id, graph_id, graph_version, graph_ref, "
            "graph_checksum, node_id, and node_instance_id"
        )
    identity = GraphStageIdentity(
        run_id=run_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_ref=graph_ref,
        graph_checksum=graph_checksum,
        node_id=node_id,
        node_instance_id=node_instance_id,
    )
    for field_name, value in identity.to_dict().items():
        if value != {"run_id": run_id, **graph_values}[field_name]:
            raise ValueError(f"{field_name} must be canonical")
    if (activity_id is None) != (attempt is None):
        raise ValueError("activity artifact lineage requires both activity_id and attempt")
    if activity_id is not None:
        execution = GraphExecutionIdentity(
            **identity.to_dict(),
            activity_id=activity_id,
            attempt=attempt,
        )
        if execution.activity_id != activity_id or execution.attempt != attempt:
            raise ValueError("activity artifact lineage must be canonical")
    if graph_checkpoint_ref is not None:
        _required_string(graph_checkpoint_ref, "graph_checkpoint_ref")
    return identity.graph_id, identity.graph_version


def canonical_artifact_relative_path(
    artifact: ArtifactRef | ArtifactWriteRequest,
    *,
    artifact_id: str | None = None,
) -> str:
    """Derive the only live filesystem location from immutable artifact identity."""

    resolved_id = artifact_id or artifact.artifact_id
    if resolved_id is None:
        raise ValueError("artifact_id is required for a canonical artifact path")
    _required_string(resolved_id, "artifact_id")
    extension = _extension_for_content_type(artifact.content_type)
    identity_digest = hash_text(
        artifact_identity_key(artifact, artifact_id=resolved_id)
    )
    return f"objects/{identity_digest}{extension}"


def artifact_identity_key(
    artifact: ArtifactRef | ArtifactWriteRequest,
    *,
    artifact_id: str | None = None,
) -> str:
    """Return the collision-free persisted key for one artifact identity."""

    resolved_id = artifact_id or artifact.artifact_id
    _required_identity_string(resolved_id, "artifact_id")
    values = [artifact.scope_kind, artifact.run_id]
    if artifact.scope_kind == ARTIFACT_SCOPE_GRAPH:
        values.extend(
            [
                artifact.graph_id,
                artifact.graph_version,
                artifact.graph_ref,
                artifact.graph_checksum,
                artifact.node_id,
                artifact.node_instance_id,
                artifact.graph_checkpoint_ref,
                artifact.activity_id,
                artifact.attempt,
            ]
        )
    values.append(resolved_id)
    return "\x1f".join("" if value is None else str(value) for value in values)


def _extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "application/json": ".json",
        "application/x-ndjson": ".jsonl",
        "text/markdown": ".md",
        "text/plain": ".txt",
    }.get(normalized, ".bin")


def _require_exact_payload_fields(
    payload: dict[str, Any],
    expected: set[str],
    model: str,
) -> None:
    if not isinstance(payload, dict):
        raise TypeError(f"{model} payload must be an object")
    actual = set(payload)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields: {unknown}")
        if missing:
            details.append(f"missing fields: {missing}")
        raise ValueError(f"{model} fields are invalid ({'; '.join(details)})")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} is required")
    return value


def _required_identity_string(value: Any, field: str) -> str:
    value = _required_string(value, field)
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field} contains a control character")
    return value


def _required_payload_string(payload: dict[str, Any], field: str) -> str:
    return _required_string(payload.get(field), field)


def _optional_validated_run_id(value: Any) -> str | None:
    if value is None:
        return None
    return validate_artifact_path_segment(value, field="run_id")


def _required_alias_string(
    payload: dict[str, Any],
    primary: str,
    legacy: str,
) -> str:
    primary_value = payload.get(primary)
    legacy_value = payload.get(legacy)
    if primary_value is not None and legacy_value is not None:
        primary_string = _required_string(primary_value, primary)
        legacy_string = _required_string(legacy_value, legacy)
        if primary_string != legacy_string:
            raise ValueError(f"conflicting {primary}/{legacy} values")
        return primary_string
    value = primary_value if primary_value is not None else legacy_value
    return _required_string(value, primary)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_attempt(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("attempt must be an integer")
    return value
