from __future__ import annotations

import os
from pathlib import Path

from domain.sources import SourceDefinition
from sources import SourceConfigError, SourceRegistry, load_source_fetch_policy, load_source_registry
from sources.connectors import SourceFetchPolicy


def build_default_source_registry(*, source_config_path: str | Path | None = None) -> SourceRegistry:
    configured_path, required = _default_source_config_path(source_config_path)
    if configured_path is not None:
        if not configured_path.exists():
            if required:
                raise SourceConfigError(f"source config file does not exist: {configured_path}")
        else:
            return load_source_registry(configured_path)
    return SourceRegistry(
        [
            SourceDefinition(
                source_id="openai-news",
                name="OpenAI News",
                source_type="rss",
                url="https://openai.com/news/rss.xml",
                reliability="high",
                authority_score=0.9,
                topics=["ai", "models"],
            ),
            SourceDefinition(
                source_id="google-ai-blog",
                name="Google AI Blog",
                source_type="rss",
                url="https://blog.google/technology/ai/rss/",
                reliability="high",
                authority_score=0.85,
                topics=["ai", "research"],
            ),
        ]
    )


def build_default_source_fetch_policy(
    *,
    source_config_path: str | Path | None = None,
) -> SourceFetchPolicy:
    configured_path, required = _default_source_config_path(source_config_path)
    if configured_path is not None:
        if not configured_path.exists():
            if required:
                raise SourceConfigError(f"source config file does not exist: {configured_path}")
        else:
            return load_source_fetch_policy(configured_path)
    return SourceFetchPolicy()


def ensure_live_source_registry(source_registry: SourceRegistry) -> None:
    validation = source_registry.validate()
    if validation.is_valid:
        return
    issues = "; ".join(
        f"{issue.source_id}.{issue.field}: {issue.message}"
        for issue in validation.errors
    )
    raise SourceConfigError(f"live source registry validation failed: {issues}")


def _default_source_config_path(path: str | Path | None) -> tuple[Path | None, bool]:
    if path is not None:
        return Path(path), True
    env_path = os.getenv("NEWS_SOURCES_CONFIG")
    if env_path:
        return Path(env_path), True
    default_path = Path("configs/sources.yaml")
    if default_path.exists():
        return default_path, False
    return None, False
