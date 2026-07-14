from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.artifacts.paths import validate_artifact_path_segment
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


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
    step_id: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    redacted: bool = True
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def uri(self) -> str:
        return self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
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
        return cls(
            artifact_id=_required_payload_string(payload, "artifact_id"),
            run_id=_required_payload_string(payload, "run_id"),
            step_id=_optional_str(payload.get("step_id")),
            artifact_type=_required_payload_string(payload, "artifact_type"),
            path=_required_alias_string(payload, "path", "uri"),
            content_type=_required_alias_string(payload, "content_type", "media_type"),
            size_bytes=_optional_int(payload.get("size_bytes")),
            checksum=_optional_str(payload.get("checksum") or payload.get("content_hash")),
            redacted=bool(payload.get("redacted", True)),
            created_at=parse_datetime(payload.get("created_at")) or utc_now(),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ArtifactWriteRequest:
    run_id: str
    artifact_type: str
    content: bytes | str
    content_type: str = "application/octet-stream"
    artifact_id: str | None = None
    step_id: str | None = None
    relative_path: str | None = None
    redacted: bool = True
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())
        object.__setattr__(self, "metadata", dict(self.metadata))

    def content_bytes(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        return self.content.encode("utf-8")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
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
