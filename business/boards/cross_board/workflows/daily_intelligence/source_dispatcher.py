from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from business.foundation.models.source import (
    SourceDefinition,
    SourceError,
    SourceFetchPolicy,
    SourceFetchRequest,
    SourceFetchResult,
    SourceReliability,
    SourceType,
    Lineage,
    RawSourceItem,
)
from business.foundation.registry.source_registry import SourceRegistry
from infrastructure.external import sources as infra_sources
from infrastructure.external.sources.models import SourceDefinition as InfraSourceDefinition
from infrastructure.external.sources.models import (
    SourceReliability as InfraSourceReliability,
    SourceType as InfraSourceType,
)
from business.layers.signal.source_tool_runtime import effective_source_fetch_policy
from business.boards.cross_board.workflows.daily_intelligence.source_connector_adapter import (
    connector_display_name,
    fetch_with_registered_connector,
    registered_connector_for_source,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_names import source_connector_name
from business.boards.cross_board.workflows.daily_intelligence.source_connector_options import (
    SourceConnectorRuntimeOptions,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_ports import (
    DailyArxivSourceConnector,
    DailyDevToSourceConnector,
    DailyFeedSourceConnector,
    DailyGithubSourceConnector,
    DailyHackerNewsSourceConnector,
    DailyHtmlSourceConnector,
    DailyLobstersSourceConnector,
    DailyManualSourceConnector,
    DailyMediumSourceConnector,
    DailyRedditSourceConnector,
    DailyStackOverflowSourceConnector,
)
from business.boards.cross_board.workflows.daily_intelligence.source_official_blog import fetch_official_blog


FetchHandler = Callable[
    [
        SourceDefinition,
        dict[str, Any],
        SourceFetchRequest,
        str,
        int,
        SourceConnectorRuntimeOptions,
    ],
    tuple[list[Any], list[SourceError], SourceFetchResult | None],
]


@dataclass(slots=True)
class SourceDispatcher:
    source_registry: SourceRegistry
    feed_connector: DailyFeedSourceConnector
    html_connector: DailyHtmlSourceConnector
    manual_connector: DailyManualSourceConnector
    arxiv_connector: DailyArxivSourceConnector
    github_connector: DailyGithubSourceConnector
    hackernews_connector: DailyHackerNewsSourceConnector
    reddit_connector: DailyRedditSourceConnector
    lobsters_connector: DailyLobstersSourceConnector
    stackoverflow_connector: DailyStackOverflowSourceConnector
    devto_connector: DailyDevToSourceConnector
    medium_connector: DailyMediumSourceConnector
    _fetch_handlers: dict[SourceType, FetchHandler] = field(init=False, repr=False)
    _connector_handlers: dict[SourceType, Callable[[], Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._fetch_handlers: dict[SourceType, FetchHandler] = {
            SourceType.RSS: self._fetch_feed,
            SourceType.ATOM: self._fetch_feed,
            SourceType.OFFICIAL_BLOG: self._fetch_official_blog,
            SourceType.HTML: self._fetch_html,
            SourceType.WEB_PAGE: self._fetch_html,
            SourceType.MANUAL: self._fetch_manual,
            SourceType.ARXIV: self._fetch_arxiv,
            SourceType.GITHUB: self._fetch_github,
            SourceType.HACKERNEWS: self._fetch_hackernews,
            SourceType.REDDIT: self._fetch_reddit,
            SourceType.LOBSTERS: self._fetch_lobsters,
            SourceType.STACKOVERFLOW: self._fetch_stackoverflow,
            SourceType.DEVTO: self._fetch_devto,
            SourceType.MEDIUM: self._fetch_medium,
        }
        self._connector_handlers: dict[SourceType, Callable[[], Any]] = {
            SourceType.RSS: lambda: self.feed_connector,
            SourceType.ATOM: lambda: self.feed_connector,
            SourceType.OFFICIAL_BLOG: lambda: self.feed_connector,
            SourceType.HTML: lambda: self.html_connector,
            SourceType.WEB_PAGE: lambda: self.html_connector,
            SourceType.MANUAL: lambda: self.manual_connector,
            SourceType.ARXIV: lambda: self.arxiv_connector,
            SourceType.GITHUB: lambda: self.github_connector,
            SourceType.HACKERNEWS: lambda: self.hackernews_connector,
            SourceType.REDDIT: lambda: self.reddit_connector,
            SourceType.LOBSTERS: lambda: self.lobsters_connector,
            SourceType.STACKOVERFLOW: lambda: self.stackoverflow_connector,
            SourceType.DEVTO: lambda: self.devto_connector,
            SourceType.MEDIUM: lambda: self.medium_connector,
        }

    def fetch_source(
        self,
        source: SourceDefinition,
        *,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions | None = None,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        fetch_policy = self.fetch_policy_for_source(source)
        allowlist_error = _source_domain_allowlist_error(source, fetch_policy)
        if allowlist_error is not None:
            return [], [allowlist_error], None

        registered_result = fetch_with_registered_connector(
            self.source_registry,
            source,
            request=request,
            fetch_request=fetch_request,
            profile=profile,
        )
        if registered_result is not None:
            return registered_result

        handler = self._fetch_handlers.get(_source_type(source))
        if handler is not None:
            options = connector_options or SourceConnectorRuntimeOptions.from_source(source, request=request)
            return handler(source, request, fetch_request, profile, limit, options)

        return self._unsupported_source_type(source)

    def _fetch_feed(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.feed_connector.fetch(_infra_source(source), limit=limit))

    def _fetch_official_blog(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        items, errors = fetch_official_blog(
            feed_connector=self.feed_connector,
            html_connector=self.html_connector,
            source=source,
            limit=limit,
        )
        return items, errors, None

    def _fetch_html(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.html_connector.fetch(_infra_source(source), limit=limit))

    def _fetch_manual(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        manual_records = connector_options.manual_records
        return _connector_result(
            self.manual_connector.fetch(
                _infra_source(source),
                records=manual_records.records if manual_records is not None else None,
                limit=limit,
            )
        )

    def _fetch_arxiv(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(
            self.arxiv_connector.fetch(
                _infra_source(source),
                query=connector_options.query,
                limit=limit,
            )
        )

    def _fetch_github(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.github_connector.fetch(
            _infra_source(source),
            repository=connector_options.repository,
            query=connector_options.query,
            mode=connector_options.github_mode,
            limit=limit,
        ))

    def _fetch_hackernews(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.hackernews_connector.fetch(
            _infra_source(source),
            story_list=connector_options.story_list,
            limit=limit,
        ))

    def _fetch_reddit(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.reddit_connector.fetch(
            _infra_source(source),
            subreddit=connector_options.subreddit,
            listing=connector_options.listing,
            time_range=connector_options.time_range,
            limit=limit,
        ))

    def _fetch_lobsters(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.lobsters_connector.fetch(
            _infra_source(source),
            tag=connector_options.tag,
            limit=limit,
        ))

    def _fetch_stackoverflow(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.stackoverflow_connector.fetch(
            _infra_source(source),
            tag=connector_options.tag,
            site=connector_options.site,
            limit=limit,
        ))

    def _fetch_devto(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.devto_connector.fetch(
            _infra_source(source),
            tag=connector_options.tag,
            limit=limit,
        ))

    def _fetch_medium(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
        connector_options: SourceConnectorRuntimeOptions,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return _connector_result(self.medium_connector.fetch(
            _infra_source(source),
            tag=connector_options.tag,
            limit=limit,
        ))

    def _unsupported_source_type(
        self,
        source: SourceDefinition,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        return (
            [],
            [
                SourceError(
                    source_id=source.source_id,
                    source_name=source.name,
                    error_type="unsupported_source_type",
                    error_message=f"unsupported source type: {_source_type(source).value}",
                    url=source.url,
                    retryable=False,
                    metadata={
                        "retryable": False,
                        "source_health_affecting": False,
                        "workflow_blocking": False,
                    },
                )
            ],
            None,
        )

    def _registered_connector_for_source(self, source: SourceDefinition) -> Any | None:
        return registered_connector_for_source(self.source_registry, source)

    def connector_name_for_source(self, source: SourceDefinition) -> str:
        connector = self._registered_connector_for_source(source)
        if connector is not None:
            return connector_display_name(connector)
        return source_connector_name(source)

    def fetch_policy_for_source(self, source: SourceDefinition) -> SourceFetchPolicy | None:
        connector = self._connector_for_source(source)
        policy = getattr(connector, "fetch_policy", None)
        if policy is None and _source_type(source) == SourceType.MEDIUM:
            feed_connector = getattr(connector, "feed_connector", None)
            policy = getattr(feed_connector, "fetch_policy", None)
        if policy is not None:
            return effective_source_fetch_policy(_business_fetch_policy(policy), source)
        return None

    def _connector_for_source(self, source: SourceDefinition) -> Any:
        registered_connector = self._registered_connector_for_source(source)
        if registered_connector is not None:
            return registered_connector
        handler = self._connector_handlers.get(_source_type(source))
        return handler() if handler is not None else None


def _source_type(source: SourceDefinition) -> SourceType:
    return SourceType(source.source_type)


def _source_reliability(source: SourceDefinition) -> SourceReliability:
    return SourceReliability(source.reliability)


def _infra_source(source: SourceDefinition) -> InfraSourceDefinition:
    return InfraSourceDefinition(
        source_id=source.source_id,
        name=source.name,
        source_type=InfraSourceType(_source_type(source).value),
        url=source.url,
        reliability=InfraSourceReliability(_source_reliability(source).value),
        authority_score=source.authority_score,
        enabled=source.enabled,
        fetch_interval_seconds=source.fetch_interval_seconds,
        respect_robots=source.respect_robots,
        user_agent=source.user_agent,
        topics=list(source.topics),
        category=source.category,
        language=source.language,
        region=source.region,
        metadata=dict(source.metadata),
    )


def _business_fetch_policy(policy: Any) -> SourceFetchPolicy:
    if isinstance(policy, SourceFetchPolicy):
        return policy
    return SourceFetchPolicy(
        timeout_seconds=policy.timeout_seconds,
        max_bytes=policy.max_bytes,
        max_redirects=policy.max_redirects,
        user_agent=policy.user_agent,
        respect_robots=policy.respect_robots,
        rate_limit_per_domain_per_minute=policy.rate_limit_per_domain_per_minute,
        allowed_domains=tuple(getattr(policy, "allowed_domains", ()) or ()),
        retry_times=policy.retry_times,
        retry_on_status_codes=tuple(policy.retry_on_status_codes),
    )


def _source_domain_allowlist_error(
    source: SourceDefinition,
    fetch_policy: SourceFetchPolicy | None,
) -> SourceError | None:
    allowed_domains = tuple(getattr(fetch_policy, "allowed_domains", ()) or ())
    if not allowed_domains:
        return None
    host = (urlsplit(source.url).hostname or "").casefold()
    if _host_matches_allowed_domain(host, allowed_domains):
        return None
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="source_domain_not_allowed",
        error_message=(
            "source URL host is not allowed by fetch policy allowed_domains: "
            f"{host or '<missing>'}"
        ),
        url=source.url,
        retryable=False,
        metadata={
            "phase": "fetch",
            "retryable": False,
            "source_health_affecting": False,
            "workflow_blocking": False,
            "domain": host,
            "allowed_domains": list(allowed_domains),
        },
    )


def _host_matches_allowed_domain(host: str, allowed_domains: tuple[str, ...]) -> bool:
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def _connector_result(
    result: tuple[list[infra_sources.RawSourceItem], list[infra_sources.SourceError]],
) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
    items, errors = result
    return (
        [_business_raw_item(item) for item in items],
        [_business_source_error(error) for error in errors],
        None,
    )


def _business_raw_item(item: infra_sources.RawSourceItem) -> Any:
    payload = item.to_dict()
    lineage_payload = payload.pop("lineage", None)
    return RawSourceItem(
        **payload,
        lineage=(
            Lineage.from_dict(lineage_payload)
            if isinstance(lineage_payload, dict)
            else None
        ),
    )


def _business_source_error(error: infra_sources.SourceError) -> SourceError:
    return SourceError(
        source_id=error.source_id,
        source_name=error.source_name,
        error_type=error.error_type,
        error_message=error.error_message,
        url=error.url,
        retryable=error.retryable,
        request_ref=error.request_ref,
        response_ref=error.response_ref,
        occurred_at=error.occurred_at,
        metadata=dict(error.metadata),
    )


