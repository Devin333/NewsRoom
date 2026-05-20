from __future__ import annotations

from pathlib import Path

from infrastructure.external.source_adapters import (
    SourceConfigError,
    SourceFetchPolicy,
    SourceRegistry,
    build_default_source_fetch_policy as _build_default_source_fetch_policy,
    build_default_source_registry as _build_default_source_registry,
)


def build_default_source_registry(*, source_config_path: str | Path | None = None) -> SourceRegistry:
    # TODO(boundary-migration): legacy adapter, remove after business board services are stable.
    return _build_default_source_registry(source_config_path=source_config_path)


def build_default_source_fetch_policy(
    *,
    source_config_path: str | Path | None = None,
) -> SourceFetchPolicy:
    # TODO(boundary-migration): legacy adapter, remove after business board services are stable.
    return _build_default_source_fetch_policy(source_config_path=source_config_path)


def ensure_live_source_registry(source_registry: SourceRegistry) -> None:
    validation = source_registry.validate()
    if validation.is_valid:
        return
    issues = "; ".join(
        f"{issue.source_id}.{issue.field}: {issue.message}"
        for issue in validation.errors
    )
    raise SourceConfigError(f"live source registry validation failed: {issues}")
