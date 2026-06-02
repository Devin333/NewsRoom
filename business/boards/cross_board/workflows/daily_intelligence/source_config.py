from __future__ import annotations

from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_config import (
    SourceConfigError,
)


def ensure_live_source_registry(source_registry: SourceRegistry) -> None:
    validation = source_registry.validate()
    if validation.is_valid:
        return
    issues = "; ".join(
        f"{issue.source_id}.{issue.field}: {issue.message}"
        for issue in validation.errors
    )
    raise SourceConfigError(f"live source registry validation failed: {issues}")


__all__ = ["ensure_live_source_registry"]
