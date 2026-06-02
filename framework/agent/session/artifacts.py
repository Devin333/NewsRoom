"""Artifact references for large session inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SessionArtifactRef:
    """Reference to a large object stored outside shared session content."""

    artifact_id: str
    artifact_type: str
    uri: str
    mime_type: str | None = None
    digest: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.artifact_id or "").strip():
            raise ValueError("artifact_id is required")
        if not str(self.artifact_type or "").strip():
            raise ValueError("artifact_type is required")
        if not str(self.uri or "").strip():
            raise ValueError("uri is required")
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
