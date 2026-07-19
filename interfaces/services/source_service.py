from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from business.foundation.models.source import (
    SourceDefinition,
    SourceError as BusinessSourceError,
    SourceFetchPolicy as BusinessSourceFetchPolicy,
    SourceReliability as BusinessSourceReliability,
    SourceType as BusinessSourceType,
)
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
from interfaces.services.source_health_probe import default_source_health_probe
from interfaces.services.source_mapping import (
    to_business_fetch_policy as _business_fetch_policy,
    to_business_raw_source_item as _business_raw_item,
    to_business_source_error as _business_source_error,
    to_infrastructure_fetch_policy as _infra_fetch_policy,
    to_infrastructure_source_definition as _infra_source,
)
from business.layers.signal.source_router import SourceConnectorRouter
from business.layers.signal.source_catalog import SOURCE_CATEGORIES, SOURCE_PRIORITIES
from business.foundation.models.source import SourceHealth
from infrastructure.external.sources import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    DomainRateLimiter,
    FeedConnector,
    HackerNewsConnector,
    HtmlConnector,
    LobstersConnector,
    ManualConnector,
    MediumConnector,
    RedditConnector,
    RawSourceItem,
    SourceError,
    SourceFetchPolicy as InfraSourceFetchPolicy,
    StackOverflowConnector,
    DevToConnector,
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
    request_id: str | None = None

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


@dataclass(frozen=True)
class SourceBatchFetchResult:
    source_count: int
    item_count: int
    error_count: int
    skipped_count: int
    results: list[SourceFetchPreviewResult]
    selection_report: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.error_count == 0,
            "source_count": self.source_count,
            "item_count": self.item_count,
            "error_count": self.error_count,
            "skipped_count": self.skipped_count,
            "results": [result.to_dict() for result in self.results],
            "selection_report": (
                self.selection_report.to_dict()
                if self.selection_report is not None and hasattr(self.selection_report, "to_dict")
                else self.selection_report
            ),
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
        fetch_policy: BusinessSourceFetchPolicy | InfraSourceFetchPolicy | None = None,
        rate_limiter: Any | None = None,
        arxiv_connector: Any | None = None,
        github_connector: Any | None = None,
        source_router: SourceConnectorRouter | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        explicit_components = any(
            component is not None
            for component in (source_registry, arxiv_connector, github_connector, source_router)
        )
        if source_registry is None:
            source_registry = build_default_source_registry(source_config_path=source_config_path)
        if fetch_policy is None:
            fetch_policy = build_default_source_fetch_policy(source_config_path=source_config_path)
        self.source_registry = source_registry
        self._request_id_factory = request_id_factory or _new_source_request_id
        self.fetch_policy = _infra_fetch_policy(fetch_policy)
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.source_health_store = source_health_store or (
            None if explicit_components else source_health_store_from_env()
        )
        self.health_manager = health_manager or BasicSourceHealthManager(
            health_store=self.source_health_store
        )
        self.health_probe_fetcher = health_probe_fetcher or default_source_health_probe
        self.arxiv_connector = arxiv_connector or default_arxiv_connector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.github_connector = github_connector or default_github_connector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.source_router = source_router or SourceConnectorRouter(
            feed_connector=FeedConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            arxiv_connector=self.arxiv_connector,
            github_connector=self.github_connector,
            hackernews_connector=HackerNewsConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            reddit_connector=RedditConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            lobsters_connector=LobstersConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            stackoverflow_connector=StackOverflowConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            devto_connector=DevToConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            medium_connector=MediumConnector(
                feed_connector=FeedConnector(
                    fetch_policy=self.fetch_policy,
                    rate_limiter=self.rate_limiter,
                )
            ),
            html_connector=HtmlConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            ),
            manual_connector=ManualConnector(),
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
                    source_type=BusinessSourceType(source.source_type).value,
                    url=source.url,
                    reliability=BusinessSourceReliability(source.reliability).value,
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

    def source_categories(self) -> dict[str, Any]:
        return {"categories": list(SOURCE_CATEGORIES), "category_count": len(SOURCE_CATEGORIES)}

    def source_priorities(self) -> dict[str, Any]:
        return {"priorities": list(SOURCE_PRIORITIES), "priority_count": len(SOURCE_PRIORITIES)}

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
            fetch_policy=_business_fetch_policy(self.fetch_policy),
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
        request_id = self._request_id_factory()
        blocked_result = self._blocked_preview_result(
            source,
            query=query,
            request_id=request_id,
        )
        if blocked_result is not None:
            return blocked_result
        items, errors = self.arxiv_connector.fetch(_infra_source(source), query=query, limit=limit)
        errors = _with_request_id(errors, request_id=request_id)
        self._record_preview_health(source, items=items, errors=errors)
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=BusinessSourceType(source.source_type).value,
            query=query,
            items=items,
            errors=errors,
            request_id=request_id,
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
        request_id = self._request_id_factory()
        blocked_result = self._blocked_preview_result(
            source,
            query=repository,
            request_id=request_id,
        )
        if blocked_result is not None:
            return blocked_result
        items, errors = self.github_connector.fetch_releases(
            _infra_source(source),
            repository=repository,
            limit=limit,
        )
        errors = _with_request_id(errors, request_id=request_id)
        self._record_preview_health(source, items=items, errors=errors)
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=BusinessSourceType(source.source_type).value,
            query=repository,
            items=items,
            errors=errors,
            request_id=request_id,
        )

    def fetch_source(
        self,
        *,
        source_id: str,
        limit: int = 10,
        query: str | None = None,
        force: bool = False,
    ) -> SourceFetchPreviewResult:
        if not source_id:
            raise ValueError("source_id is required")
        _validate_limit(limit, field_name="limit")
        try:
            source = self.source_registry.get(source_id)
        except KeyError as exc:
            raise KeyError(f"source not found: {source_id}") from exc
        return self._fetch_configured_source(source, limit=limit, query=query, force=force)

    def fetch_category(
        self,
        *,
        category: str,
        limit_per_source: int = 5,
        enabled_only: bool = True,
        priority: str | None = None,
        language: str | None = None,
        region: str | None = None,
        force: bool = False,
    ) -> SourceBatchFetchResult:
        if not category:
            raise ValueError("category is required")
        _validate_limit(limit_per_source, field_name="limit_per_source")
        sources = self.source_registry.list_by_category(category, enabled_only=enabled_only)
        sources = _filter_sources(sources, priority=priority, language=language, region=region)
        return self._fetch_batch(sources, limit_per_source=limit_per_source, force=force)

    def fetch_priority(
        self,
        *,
        priority: str,
        limit_per_source: int = 5,
        enabled_only: bool = True,
        force: bool = False,
    ) -> SourceBatchFetchResult:
        if not priority:
            raise ValueError("priority is required")
        _validate_limit(limit_per_source, field_name="limit_per_source")
        sources = _filter_sources(
            self.source_registry.list_sources(enabled_only=enabled_only),
            priority=priority,
        )
        return self._fetch_batch(sources, limit_per_source=limit_per_source, force=force)

    def fetch_topic_sources(
        self,
        *,
        topic: str,
        limit_per_source: int = 5,
        enabled_only: bool = True,
        category: str | None = None,
        priority: str | None = None,
        language: str | None = None,
        region: str | None = None,
        force: bool = False,
    ) -> SourceBatchFetchResult:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is required")
        _validate_limit(limit_per_source, field_name="limit_per_source")
        selected, report = self.source_registry.select_sources_with_report(
            topic=topic,
            enabled_only=enabled_only,
            language=language,
            region=region,
            category=category,
        )
        filtered = _filter_sources(selected, priority=priority)
        if priority is not None:
            report = self.source_registry.selection_report(
                topic=topic,
                selected_sources=filtered,
                filters={
                    "enabled_only": enabled_only,
                    "language": language,
                    "region": region,
                    "category": category,
                    "priority": priority,
                    "fallback_to_enabled": True,
                },
                matched_source_count=len(filtered),
                fallback_used=report.fallback_used,
                fallback_reason=report.fallback_reason,
            )
        return self._fetch_batch(
            filtered,
            limit_per_source=limit_per_source,
            force=force,
            selection_report=report,
        )

    def _fetch_batch(
        self,
        sources: list[SourceDefinition],
        *,
        limit_per_source: int,
        force: bool,
        selection_report: Any | None = None,
    ) -> SourceBatchFetchResult:
        results = [
            self._fetch_configured_source(
                source,
                limit=limit_per_source,
                query=None,
                force=force,
            )
            for source in sources
        ]
        item_count = sum(len(result.items) for result in results)
        error_count = sum(len(result.errors) for result in results)
        skipped_count = sum(1 for result in results if _preview_result_skipped(result))
        return SourceBatchFetchResult(
            source_count=len(sources),
            item_count=item_count,
            error_count=error_count,
            skipped_count=skipped_count,
            results=results,
            selection_report=selection_report,
        )

    def _fetch_configured_source(
        self,
        source: SourceDefinition,
        *,
        limit: int,
        query: str | None,
        force: bool,
    ) -> SourceFetchPreviewResult:
        actual_query = _query_for_source(source, query=query)
        request_id = self._request_id_factory()
        blocked_result = self._blocked_preview_result(
            source,
            query=actual_query,
            request_id=request_id,
            force=force,
        )
        if blocked_result is not None:
            return blocked_result
        try:
            items, errors = self.source_router.fetch(source, query=query, limit=limit)
        except ValueError as exc:
            items = []
            errors = [
                SourceError(
                    source_id=source.source_id,
                    source_name=source.name,
                    error_type="unsupported_source_type",
                    error_message=str(exc),
                    url=source.url,
                    retryable=False,
                    metadata={
                        "phase": "fetch",
                        "retryable": False,
                        "source_health_affecting": False,
                    },
                )
            ]
        errors = _with_request_id(errors, request_id=request_id)
        self._record_preview_health(source, items=items, errors=errors)
        return SourceFetchPreviewResult(
            source_id=source.source_id,
            source_type=BusinessSourceType(source.source_type).value,
            query=actual_query,
            items=items,
            errors=errors,
            request_id=request_id,
        )

    def _blocked_preview_result(
        self,
        source: SourceDefinition,
        *,
        query: str,
        request_id: str,
        force: bool = False,
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
                source_type=BusinessSourceType(source.source_type).value,
                query=query,
                items=[],
                errors=_with_request_id([error], request_id=request_id),
                request_id=request_id,
            )
        if force:
            return None
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
            source_type=BusinessSourceType(source.source_type).value,
            query=query,
            items=[],
            errors=_with_request_id([error], request_id=request_id),
            request_id=request_id,
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
                _business_source_error(health_error),
                source_name=source.name,
                url=source.url,
            )


def _raw_item_to_dict(item: RawSourceItem) -> dict[str, Any]:
    return _business_raw_item(item).to_dict()


def _with_request_id(
    errors: list[SourceError],
    *,
    request_id: str,
) -> list[SourceError]:
    return [
        replace(
            error,
            metadata={**error.metadata, "request_id": request_id},
        )
        for error in errors
    ]


def _new_source_request_id() -> str:
    return f"source-request-{uuid4()}"


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


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _source_summary_model(source: SourceDefinition) -> SourceSummary:
    return SourceSummary(
        source_id=source.source_id,
        name=source.name,
        source_type=BusinessSourceType(source.source_type).value,
        url=source.url,
        reliability=BusinessSourceReliability(source.reliability).value,
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


def _validate_limit(value: int, *, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


def _filter_sources(
    sources: list[SourceDefinition],
    *,
    priority: str | None = None,
    language: str | None = None,
    region: str | None = None,
) -> list[SourceDefinition]:
    filtered = list(sources)
    if priority is not None:
        expected = _normalize_catalog_value(priority)
        filtered = [
            source
            for source in filtered
            if _normalize_catalog_value(source.metadata.get("priority")) == expected
        ]
    if language is not None:
        filtered = [source for source in filtered if source.language == language]
    if region is not None:
        filtered = [source for source in filtered if source.region == region]
    return filtered


def _normalize_catalog_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    return text or None


def _query_for_source(source: SourceDefinition, *, query: str | None) -> str:
    if query is not None and query.strip():
        return query.strip()
    for key in ("query", "repository", "subreddit", "tagged", "tag", "story_list"):
        value = source.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _preview_result_skipped(result: SourceFetchPreviewResult) -> bool:
    return any(error.error_type == "source_fetch_skipped" for error in result.errors)
