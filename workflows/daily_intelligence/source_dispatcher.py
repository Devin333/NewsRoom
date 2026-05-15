from __future__ import annotations

from dataclasses import dataclass
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
        if source.source_type in {SourceType.RSS, SourceType.ATOM}:
            items, errors = self.feed_connector.fetch(source, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.OFFICIAL_BLOG:
            items, errors = fetch_official_blog(
                feed_connector=self.feed_connector,
                html_connector=self.html_connector,
                source=source,
                limit=limit,
            )
            return items, errors, None
        if source.source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            items, errors = self.html_connector.fetch(source, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.MANUAL:
            items, errors = self.manual_connector.fetch(source, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.ARXIV:
            query = str(source.metadata.get("query") or request["topic"])
            items, errors = self.arxiv_connector.fetch(source, query=query, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.GITHUB:
            repository = source.metadata.get("repository")
            query = source.metadata.get("query") or request.get("topic")
            items, errors = self.github_connector.fetch(
                source,
                repository=str(repository) if repository is not None else None,
                query=str(query) if query is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.HACKERNEWS:
            story_list = source.metadata.get("story_list")
            items, errors = self.hackernews_connector.fetch(
                source,
                story_list=str(story_list) if story_list is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.REDDIT:
            subreddit = source.metadata.get("subreddit")
            listing = source.metadata.get("listing")
            items, errors = self.reddit_connector.fetch(
                source,
                subreddit=str(subreddit) if subreddit is not None else None,
                listing=str(listing) if listing is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.LOBSTERS:
            tag = source.metadata.get("tag")
            items, errors = self.lobsters_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.STACKOVERFLOW:
            tag = source.metadata.get("tagged") or source.metadata.get("tag")
            site = source.metadata.get("site")
            items, errors = self.stackoverflow_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                site=str(site) if site is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.DEVTO:
            tag = source.metadata.get("tag")
            items, errors = self.devto_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.MEDIUM:
            tag = source.metadata.get("tag")
            items, errors = self.medium_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                limit=limit,
            )
            return items, errors, None
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
        if source.source_type in {SourceType.RSS, SourceType.ATOM, SourceType.OFFICIAL_BLOG}:
            return self.feed_connector
        if source.source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            return self.html_connector
        if source.source_type == SourceType.MANUAL:
            return self.manual_connector
        if source.source_type == SourceType.ARXIV:
            return self.arxiv_connector
        if source.source_type == SourceType.GITHUB:
            return self.github_connector
        if source.source_type == SourceType.HACKERNEWS:
            return self.hackernews_connector
        if source.source_type == SourceType.REDDIT:
            return self.reddit_connector
        if source.source_type == SourceType.LOBSTERS:
            return self.lobsters_connector
        if source.source_type == SourceType.STACKOVERFLOW:
            return self.stackoverflow_connector
        if source.source_type == SourceType.DEVTO:
            return self.devto_connector
        if source.source_type == SourceType.MEDIUM:
            return self.medium_connector
        return None


