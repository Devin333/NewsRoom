from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from domain.sources import RawSourceItem, SourceDefinition, SourceError, SourceHealth
from sources import SourceRegistry
from sources.connectors import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    ArxivConnector,
    DomainRateLimiter,
    GithubConnector,
    SourceFetchPolicy,
)
from sources.health import (
    BasicSourceHealthManager,
    SourceHealthChecker,
    SourceHealthCheckResult,
    SourceHealthStore,
)


@dataclass(frozen=True)
class SourceSummary:
    source_id: str
    name: str
    source_type: str
    url: str
    reliability: str
    authority_score: float
    enabled: bool
    respect_robots: bool
    fetch_interval_seconds: int
    topics: list[str]
    category: str | None = None
    language: str | None = None
    region: str | None = None
    user_agent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "url": self.url,
            "reliability": self.reliability,
            "authority_score": self.authority_score,
            "enabled": self.enabled,
            "respect_robots": self.respect_robots,
            "fetch_interval_seconds": self.fetch_interval_seconds,
            "topics": list(self.topics),
            "category": self.category,
            "language": self.language,
            "region": self.region,
            "user_agent": self.user_agent,
        }


@dataclass(frozen=True)
class SourceListResult:
    sources: list[SourceSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": len(self.sources),
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True)
class SourceDetailResult:
    source: SourceSummary

    def to_dict(self) -> dict[str, Any]:
        payload = self.source.to_dict()
        return {"source_id": self.source.source_id, "source": payload, **payload}


@dataclass(frozen=True)
class SourceHealthResult:
    health: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": len(self.health),
            "health": [dict(item) for item in self.health],
        }


@dataclass(frozen=True)
class SourceFetchPreviewResult:
    source_id: str
    source_type: str
    query: str
    items: list[RawSourceItem]
    errors: list[SourceError]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "query": self.query,
            "item_count": len(self.items),
            "error_count": len(self.errors),
            "items": [_raw_item_to_dict(item) for item in self.items],
            "errors": [error.to_dict() for error in self.errors],
        }


class SourceApplicationService:
    def __init__(
        self,
        *,
        source_registry: SourceRegistry | None = None,
        health_manager: BasicSourceHealthManager | None = None,
        source_health_store: SourceHealthStore | None = None,
        health_probe_fetcher=None,
        source_config_path: str | Path | None = None,
        fetch_policy: SourceFetchPolicy | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        arxiv_connector: ArxivConnector | None = None,
        github_connector: GithubConnector | None = None,
    ) -> None:
        if source_registry is None:
            from workflows.daily_intelligence.runner import build_default_source_registry

            source_registry = build_default_source_registry(source_config_path=source_config_path)
        if fetch_policy is None:
            from workflows.daily_intelligence.runner import build_default_source_fetch_policy

            fetch_policy = build_default_source_fetch_policy(source_config_path=source_config_path)
        self.source_registry = source_registry
        self.fetch_policy = fetch_policy
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.source_health_store = source_health_store or _source_health_store_from_env()
        self.health_manager = health_manager or BasicSourceHealthManager(
            health_store=self.source_health_store
        )
        self.health_probe_fetcher = health_probe_fetcher
        self.arxiv_connector = arxiv_connector or ArxivConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.github_connector = github_connector or GithubConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )

    def list_sources(
        self,
        *,
        enabled_only: bool = True,
        reliability: str | None = None,
    ) -> SourceListResult:
        sources = (
            self.source_registry.list_by_reliability(reliability, enabled_only=enabled_only)
            if reliability is not None
            else self.source_registry.list_sources(enabled_only=enabled_only)
        )
        return SourceListResult(
            [
                SourceSummary(
                    source_id=source.source_id,
                    name=source.name,
                    source_type=source.source_type.value,
                    url=source.url,
                    reliability=source.reliability.value,
                    authority_score=source.authority_score,
                    enabled=source.enabled,
                    respect_robots=source.respect_robots,
                    fetch_interval_seconds=source.fetch_interval_seconds,
                    topics=list(source.topics),
                    category=source.category,
                    language=source.language,
                    region=source.region,
                    user_agent=source.user_agent,
                )
                for source in sources
            ]
        )

    def get_source(self, source_id: str) -> SourceDetailResult:
        if not source_id:
            raise ValueError("source_id is required")
        try:
            source = self.source_registry.get(source_id)
        except KeyError as exc:
            raise KeyError(f"source not found: {source_id}") from exc
        return SourceDetailResult(_source_summary_model(source))

    def validate_sources(self):
        return self.source_registry.validate()

    def source_health(self, *, enabled_only: bool = True) -> SourceHealthResult:
        return SourceHealthResult(
            [
                self._health_for_source(source).to_dict()
                for source in self.source_registry.list_sources(enabled_only=enabled_only)
            ]
        )

    def check_source_health(
        self,
        *,
        source_id: str | None = None,
        enabled_only: bool = True,
        limit: int | None = None,
        force: bool = False,
    ) -> SourceHealthCheckResult:
        checker = SourceHealthChecker(
            self.source_registry,
            self.health_manager,
            fetch_policy=self.fetch_policy,
            probe_fetcher=self.health_probe_fetcher,
        )
        return checker.run(
            source_id=source_id,
            enabled_only=enabled_only,
            limit=limit,
            force=force,
        )

    def _health_for_source(self, source: SourceDefinition) -> SourceHealth:
        if not source.enabled:
            return self.health_manager.record_disabled(
                source.source_id,
                reason="source disabled by configuration",
                source_name=source.name,
                url=source.url,
            )
        return self.health_manager.get(
            source.source_id,
            source_name=source.name,
            url=source.url,
        )

    def fetch_arxiv(self, *, query: str, limit: int = 5) -> SourceFetchPreviewResult:
        if not query.strip():
            raise ValueError("query is required")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        source = SourceDefinition(
            source_id="arxiv",
            name="arXiv",
            source_type="arxiv",
            url=ARXIV_API_URL,
            reliability="high",
            authority_score=0.95,
            topics=["papers", "research"],
            language="en",
            metadata={"query": query.strip()},
        )
        items, errors = self.arxiv_connector.fetch(source, query=query, limit=limit)
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=source.source_type.value,
            query=query.strip(),
            items=items,
            errors=errors,
        )

    def fetch_github_releases(self, *, repository: str, limit: int = 5) -> SourceFetchPreviewResult:
        if not repository.strip():
            raise ValueError("repository is required")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        source = SourceDefinition(
            source_id="github",
            name="GitHub",
            source_type="github",
            url=GITHUB_API_URL,
            reliability="high",
            authority_score=0.9,
            topics=["github", "release", "software"],
            language="en",
            metadata={"repository": repository.strip()},
        )
        items, errors = self.github_connector.fetch_releases(
            source,
            repository=repository,
            limit=limit,
        )
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=source.source_type.value,
            query=repository.strip(),
            items=items,
            errors=errors,
        )


def _raw_item_to_dict(item: RawSourceItem) -> dict[str, Any]:
    return {
        "source_item_id": item.source_item_id,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "source_type": item.source_type.value,
        "title": item.title,
        "url": item.url,
        "fetched_at": _dt(item.fetched_at),
        "published_at": _dt(item.published_at),
        "summary": item.summary,
        "raw_content": item.raw_content,
        "authors": list(item.authors),
        "tags": list(item.tags),
        "language": item.language,
        "metadata": dict(item.metadata),
    }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _source_summary_model(source: SourceDefinition) -> SourceSummary:
    return SourceSummary(
        source_id=source.source_id,
        name=source.name,
        source_type=source.source_type.value,
        url=source.url,
        reliability=source.reliability.value,
        authority_score=source.authority_score,
        enabled=source.enabled,
        respect_robots=source.respect_robots,
        fetch_interval_seconds=source.fetch_interval_seconds,
        topics=list(source.topics),
        category=source.category,
        language=source.language,
        region=source.region,
        user_agent=source.user_agent,
    )


def _source_health_store_from_env() -> SourceHealthStore | None:
    import os

    dsn = os.environ.get("NEWS_DATABASE_DSN")
    if not dsn:
        return None
    from storage.postgres import PostgresRepository

    repository = PostgresRepository(dsn)
    repository.migrate()
    return repository
