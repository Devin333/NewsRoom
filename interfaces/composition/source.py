from __future__ import annotations

from interfaces.services.source_runtime import (
    SourceRuntimeProvider,
    build_source_runtime_composition,
)


def build_source_runtime_provider() -> SourceRuntimeProvider:
    """Create one lazy Source composition owner for an interface process root."""

    return SourceRuntimeProvider(factory=build_source_runtime_composition)


__all__ = ["build_source_runtime_provider"]
