from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

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
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ArtifactRef:
        return cls(
            artifact_id=str(payload["artifact_id"]),
            run_id=str(payload["run_id"]),
            step_id=_optional_str(payload.get("step_id")),
            artifact_type=str(payload["artifact_type"]),
            path=str(payload["path"]),
            content_type=str(payload["content_type"]),
            size_bytes=_optional_int(payload.get("size_bytes")),
            checksum=_optional_str(payload.get("checksum")),
            redacted=bool(payload.get("redacted", True)),
            created_at=_parse_datetime(str(payload["created_at"])),
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
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_bytes(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        return self.content.encode("utf-8")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
