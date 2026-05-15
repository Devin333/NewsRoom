from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from domain.sources import (
    SourceDefinition,
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourceType,
)
from sources import SourceRegistry
from sources.connectors import (
    ArxivConnector,
    FeedConnector,
    GithubConnector,
    HackerNewsConnector,
    HtmlConnector,
    LobstersConnector,
    ManualConnector,
    MediumConnector,
    RedditConnector,
    SourceFetchPolicy,
    StackOverflowConnector,
    DevToConnector,
    effective_fetch_policy,
)
from workflows.daily_intelligence.source_connector_adapter import (
    connector_display_name,
    fetch_with_registered_connector,
    registered_connector_for_source,
)
from workflows.daily_intelligence.source_connector_names import source_connector_name
from workflows.daily_intelligence.source_official_blog import fetch_official_blog


FetchHandler = Callable[
    [SourceDefinition, dict[str, Any], SourceFetchRequest, str, int],
    tuple[list[Any], list[SourceError], SourceFetchResult | None],
]


@dataclass(slots=True)
class SourceDispatcher:
    source_registry: SourceRegistry
    feed_connector: FeedConnector
    html_connector: HtmlConnector
    manual_connector: ManualConnector
    arxiv_connector: ArxivConnector
    github_connector: GithubConnector
    hackernews_connector: HackerNewsConnector
    reddit_connector: RedditConnector
    lobsters_connector: LobstersConnector
    stackoverflow_connector: StackOverflowConnector
    devto_connector: DevToConnector
    medium_connector: MediumConnector
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
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        registered_result = fetch_with_registered_connector(
            self.source_registry,
            source,
            request=request,
            fetch_request=fetch_request,
            profile=profile,
        )
        if registered_result is not None:
            return registered_result

        handler = self._fetch_handlers.get(source.source_type)
        if handler is not None:
            return handler(source, request, fetch_request, profile, limit)

        return self._unsupported_source_type(source)

    def _fetch_feed(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        items, errors = self.feed_connector.fetch(source, limit=limit)
        return items, errors, None

    def _fetch_official_blog(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
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
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        items, errors = self.html_connector.fetch(source, limit=limit)
        return items, errors, None

    def _fetch_manual(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        items, errors = self.manual_connector.fetch(source, limit=limit)
        return items, errors, None

    def _fetch_arxiv(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        query = str(source.metadata.get("query") or request["topic"])
        items, errors = self.arxiv_connector.fetch(source, query=query, limit=limit)
        return items, errors, None

    def _fetch_github(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        repository = source.metadata.get("repository")
        query = source.metadata.get("query") or request.get("topic")
        items, errors = self.github_connector.fetch(
            source,
            repository=str(repository) if repository is not None else None,
            query=str(query) if query is not None else None,
            limit=limit,
        )
        return items, errors, None

    def _fetch_hackernews(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        story_list = source.metadata.get("story_list")
        items, errors = self.hackernews_connector.fetch(
            source,
            story_list=str(story_list) if story_list is not None else None,
            limit=limit,
        )
        return items, errors, None

    def _fetch_reddit(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        subreddit = source.metadata.get("subreddit")
        listing = source.metadata.get("listing")
        items, errors = self.reddit_connector.fetch(
            source,
            subreddit=str(subreddit) if subreddit is not None else None,
            listing=str(listing) if listing is not None else None,
            limit=limit,
        )
        return items, errors, None

    def _fetch_lobsters(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        tag = source.metadata.get("tag")
        items, errors = self.lobsters_connector.fetch(
            source,
            tag=str(tag) if tag is not None else None,
            limit=limit,
        )
        return items, errors, None

    def _fetch_stackoverflow(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        tag = source.metadata.get("tagged") or source.metadata.get("tag")
        site = source.metadata.get("site")
        items, errors = self.stackoverflow_connector.fetch(
            source,
            tag=str(tag) if tag is not None else None,
            site=str(site) if site is not None else None,
            limit=limit,
        )
        return items, errors, None

    def _fetch_devto(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        tag = source.metadata.get("tag")
        items, errors = self.devto_connector.fetch(
            source,
            tag=str(tag) if tag is not None else None,
            limit=limit,
        )
        return items, errors, None

    def _fetch_medium(
        self,
        source: SourceDefinition,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        tag = source.metadata.get("tag")
        items, errors = self.medium_connector.fetch(
            source,
            tag=str(tag) if tag is not None else None,
            limit=limit,
        )
        return items, errors, None

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
                    error_message=f"unsupported source type: {source.source_type.value}",
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
        if policy is None and source.source_type == SourceType.MEDIUM:
            feed_connector = getattr(connector, "feed_connector", None)
            policy = getattr(feed_connector, "fetch_policy", None)
        if isinstance(policy, SourceFetchPolicy):
            return effective_fetch_policy(policy, source)
        return None

    def _connector_for_source(self, source: SourceDefinition) -> Any:
        registered_connector = self._registered_connector_for_source(source)
        if registered_connector is not None:
            return registered_connector
        handler = self._connector_handlers.get(source.source_type)
        return handler() if handler is not None else None


