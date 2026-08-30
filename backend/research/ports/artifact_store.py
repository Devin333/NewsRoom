from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResearchArtifactStorePort(Protocol):
    def publish(self, *, artifact_type: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
        ...


__all__ = ["ResearchArtifactStorePort"]
