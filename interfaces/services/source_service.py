from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from business.foundation.models.source import SourceDefinition
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_config import (
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from business.layers.signal.source_health import (
    BasicSourceHealthManager,
    SourceHealthChecker,
    SourceHealthCheckResult,
    SourceHealthStore,
)
from business.foundation.models.source import SourceHealth
from infrastructure.external.sources import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    DomainRateLimiter,
    RawSourceItem,
    SourceError,
    SourceFetchPolicy,
    default_arxiv_connector,
    default_github_connector,
)
from infrastructure.storage.source_health import source_health_store_from_env


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
        arxiv_connector: Any | None = None,
        github_connector: Any | None = None,
    ) -> None:
        if source_registry is None:
            source_registry = build_default_source_registry(source_config_path=source_config_path)
        if fetch_policy is None:
            fetch_policy = build_default_source_fetch_policy(source_config_path=source_config_path)
        self.source_registry = source_registry
        self.fetch_policy = fetch_policy
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.source_health_store = source_health_store or source_health_store_from_env()
        self.health_manager = health_manager or BasicSourceHealthManager(
            health_store=self.source_health_store
        )
        self.health_probe_fetcher = health_probe_fetcher
        self.arxiv_connector = arxiv_connector or default_arxiv_connector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.github_connector = github_connector or default_github_connector(
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
            rate_limiter=self.rate_limiter,
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
        query = query.strip()
        if not query:
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
            metadata={"query": query},
        )
        blocked_result = self._blocked_preview_result(source, query=query)
        if blocked_result is not None:
            return blocked_result
        items, errors = self.arxiv_connector.fetch(source, query=query, limit=limit)
        self._record_preview_health(source, items=items, errors=errors)
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=source.source_type.value,
            query=query,
            items=items,
            errors=errors,
        )

    def fetch_github_releases(self, *, repository: str, limit: int = 5) -> SourceFetchPreviewResult:
        repository = repository.strip()
        if not repository:
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
            metadata={"repository": repository},
        )
        blocked_result = self._blocked_preview_result(source, query=repository)
        if blocked_result is not None:
            return blocked_result
        items, errors = self.github_connector.fetch_releases(
            source,
            repository=repository,
            limit=limit,
        )
        self._record_preview_health(source, items=items, errors=errors)
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=source.source_type.value,
            query=repository,
            items=items,
            errors=errors,
        )

    def _blocked_preview_result(
        self,
        source: SourceDefinition,
        *,
        query: str,
    ) -> SourceFetchPreviewResult | None:
        if not source.enabled:
            health = self.health_manager.record_disabled(
                source.source_id,
                reason="source disabled by configuration",
                source_name=source.name,
                url=source.url,
            )
            error = _preview_skip_error(
                source,
                skip_reason="disabled",
                health=health.to_dict(),
                retryable=False,
            )
            return SourceFetchPreviewResult(
                source_id=source.source_id,
                source_type=source.source_type.value,
                query=query,
                items=[],
                errors=[error],
            )
        decision = self.health_manager.fetch_decision(
            source.source_id,
            source_name=source.name,
            url=source.url,
            min_interval_seconds=source.fetch_interval_seconds,
        )
        if decision.should_fetch:
            return None
        error = _preview_skip_error(
            source,
            skip_reason=decision.skip_reason or "skipped",
            health=decision.health.to_dict(),
            retryable=decision.skip_reason != "disabled",
            cooldown_until=_dt(decision.cooldown_until),
            next_fetch_at=_dt(decision.next_fetch_at),
        )
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=source.source_type.value,
            query=query,
            items=[],
            errors=[error],
        )

    def _record_preview_health(
        self,
        source: SourceDefinition,
        *,
        items: list[RawSourceItem],
        errors: list[SourceError],
    ) -> None:
        if items:
            self.health_manager.record_success(
                source.source_id,
                source_name=source.name,
                url=source.url,
            )
            return
        health_error = next(
            (
                error
                for error in errors
                if _metadata_bool(error.metadata.get("source_health_affecting"), default=True)
            ),
            None,
        )
        if health_error is not None:
            self.health_manager.record_failure(
                source.source_id,
                health_error,
                source_name=source.name,
                url=source.url,
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
        "raw_artifact_ref": _artifact_ref(item.raw_artifact_ref),
        "parse_artifact_ref": _artifact_ref(item.parse_artifact_ref),
        "authors": list(item.authors),
        "tags": list(item.tags),
        "language": item.language,
        "lineage": item.lineage.to_dict() if item.lineage else None,
        "metadata": dict(item.metadata),
    }


def _preview_skip_error(
    source: SourceDefinition,
    *,
    skip_reason: str,
    health: dict[str, Any],
    retryable: bool,
    cooldown_until: str | None = None,
    next_fetch_at: str | None = None,
) -> SourceError:
    metadata = {
        "phase": "fetch",
        "retryable": retryable,
        "source_health_affecting": False,
        "skip_reason": skip_reason,
        "health": health,
    }
    if cooldown_until is not None:
        metadata["cooldown_until"] = cooldown_until
    if next_fetch_at is not None:
        metadata["next_fetch_at"] = next_fetch_at
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="source_fetch_skipped",
        error_message=f"source preview fetch skipped: {skip_reason}",
        url=source.url,
        retryable=retryable,
        metadata=metadata,
    )


def _metadata_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _artifact_ref(value):
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


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
