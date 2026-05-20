from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class SignalArtifactRef:
    artifact_id: str
    run_id: str
    artifact_type: str
    path: str
    content_type: str
    step_id: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    redacted: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _parse_datetime(self.created_at))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

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
    def from_dict(cls, payload: dict[str, Any]) -> "SignalArtifactRef":
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
            created_at=_parse_datetime(payload["created_at"]),
            metadata=dict(payload.get("metadata") or {}),
        )


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
