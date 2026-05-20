from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from domain.sources import (
    RawSourceItem,
    SourceDefinition,
    SourceError,
    SourceHealth,
    SourceReliability,
    SourceType,
)
from sources import SourceRegistry
from sources.config import SourceConfigError, load_source_fetch_policy, load_source_registry
from sources.connectors import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    ArxivConnector,
    DomainRateLimiter,
    FeedConnector,
    GithubConnector,
    HtmlConnector,
    ManualConnector,
    SourceFetchPolicy,
    effective_fetch_policy,
    ensure_robots_allowed,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from sources.connectors.fetch_policy import rate_limited_source_error
from sources.health import (
    BasicSourceHealthManager,
    ProbeObservation,
    SourceHealthChecker,
    SourceHealthCheckEntry,
    SourceHealthCheckResult,
    SourceHealthStore,
)


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


def default_arxiv_connector(**kwargs: Any) -> ArxivConnector:
    return ArxivConnector(**kwargs)


def default_github_connector(**kwargs: Any) -> GithubConnector:
    return GithubConnector(**kwargs)


def source_health_store_from_env() -> SourceHealthStore | None:
    dsn = os.environ.get("NEWS_DATABASE_DSN")
    if not dsn:
        return None
    from storage.postgres import PostgresRepository

    repository = PostgresRepository(dsn)
    repository.migrate()
    return repository


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


__all__ = [
    "ARXIV_API_URL",
    "GITHUB_API_URL",
    "BasicSourceHealthManager",
    "DomainRateLimiter",
    "FeedConnector",
    "HtmlConnector",
    "ManualConnector",
    "ProbeObservation",
    "RawSourceItem",
    "SourceDefinition",
    "SourceError",
    "SourceFetchPolicy",
    "SourceHealth",
    "SourceHealthChecker",
    "SourceHealthCheckEntry",
    "SourceHealthCheckResult",
    "SourceHealthStore",
    "SourceRegistry",
    "SourceReliability",
    "SourceType",
    "SourceConfigError",
    "build_default_source_fetch_policy",
    "build_default_source_registry",
    "default_arxiv_connector",
    "default_github_connector",
    "effective_fetch_policy",
    "ensure_robots_allowed",
    "open_request_with_fetch_policy",
    "rate_limited_source_error",
    "run_with_fetch_retries",
    "source_health_store_from_env",
]
