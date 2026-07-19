from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class ArtifactWriteRequest:
    artifact_type: str
    payload: dict[str, Any]
    media_type: str = "application/json"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.artifact_type).strip():
            raise HarnessValidationError("artifact_type is required")
        if not str(self.media_type).strip():
            raise HarnessValidationError("media_type is required")
        object.__setattr__(self, "artifact_type", str(self.artifact_type))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "payload": to_jsonable(self.payload),
            "media_type": self.media_type,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class ArtifactRef:
    ref: str
    artifact_type: str
    checksum: str
    media_type: str = "application/json"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.ref).strip():
            raise HarnessValidationError("artifact ref is required")
        if not str(self.artifact_type).strip():
            raise HarnessValidationError("artifact_type is required")
        if not str(self.checksum).strip():
            raise HarnessValidationError("checksum is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "artifact_type": self.artifact_type,
            "checksum": self.checksum,
            "media_type": self.media_type,
            "metadata": to_jsonable(self.metadata),
        }


@runtime_checkable
class ArtifactPort(Protocol):
    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef:
        ...

    def read_artifact(self, ref: str) -> dict[str, Any]:
        ...


@runtime_checkable
class RunBoundArtifactPort(ArtifactPort, Protocol):
    def bind_run(self, run_id: str) -> AbstractContextManager[str]:
        ...


__all__ = ["ArtifactPort", "ArtifactRef", "ArtifactWriteRequest", "RunBoundArtifactPort"]
