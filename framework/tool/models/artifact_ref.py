from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    path: str | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    relative_path: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        if self.relative_path is None and self.path is not None:
            object.__setattr__(self, "relative_path", self.path)
        if self.path is None and self.relative_path is not None:
            object.__setattr__(self, "path", self.relative_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "path": self.path,
            "relative_path": self.relative_path,
            "content_type": self.content_type or "application/json",
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_any(cls, value: Any) -> "ArtifactRef":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(
                artifact_id=str(value.get("artifact_id") or ""),
                path=value.get("path"),
                relative_path=value.get("relative_path"),
                content_type=value.get("content_type"),
                size_bytes=value.get("size_bytes"),
                checksum=value.get("checksum"),
                metadata=dict(value.get("metadata") or {}),
            )
        return cls(
            artifact_id=str(getattr(value, "artifact_id", "")),
            path=getattr(value, "path", None),
            relative_path=getattr(value, "relative_path", None),
            content_type=getattr(value, "content_type", None),
            size_bytes=getattr(value, "size_bytes", None),
            checksum=getattr(value, "checksum", None),
            metadata=dict(getattr(value, "metadata", {}) or {}),
        )
