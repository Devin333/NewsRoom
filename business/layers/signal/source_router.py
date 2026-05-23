from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceDefinition, SourceError, SourceType
from infrastructure.external.sources import (
    ArxivConnector,
    DevToConnector,
    DomainRateLimiter,
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
)
from infrastructure.external.sources.models import (
    RawSourceItem,
    SourceDefinition as InfraSourceDefinition,
    SourceReliability as InfraSourceReliability,
    SourceType as InfraSourceType,
)


class SourceConnectorRouter:
    def __init__(
        self,
        *,
        feed_connector: Any | None = None,
        arxiv_connector: Any | None = None,
        github_connector: Any | None = None,
        hackernews_connector: Any | None = None,
        reddit_connector: Any | None = None,
        lobsters_connector: Any | None = None,
        stackoverflow_connector: Any | None = None,
        devto_connector: Any | None = None,
        medium_connector: Any | None = None,
        html_connector: Any | None = None,
        manual_connector: Any | None = None,
        fetch_policy: SourceFetchPolicy | None = None,
        rate_limiter: DomainRateLimiter | None = None,
    ) -> None:
        self.fetch_policy = fetch_policy or SourceFetchPolicy()
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.feed_connector = feed_connector or FeedConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.arxiv_connector = arxiv_connector or ArxivConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.github_connector = github_connector or GithubConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.hackernews_connector = hackernews_connector or HackerNewsConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.reddit_connector = reddit_connector or RedditConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.lobsters_connector = lobsters_connector or LobstersConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.stackoverflow_connector = stackoverflow_connector or StackOverflowConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.devto_connector = devto_connector or DevToConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.medium_connector = medium_connector or MediumConnector(
            feed_connector=FeedConnector(
                fetch_policy=self.fetch_policy,
                rate_limiter=self.rate_limiter,
            )
        )
        self.html_connector = html_connector or HtmlConnector(
            fetch_policy=self.fetch_policy,
            rate_limiter=self.rate_limiter,
        )
        self.manual_connector = manual_connector or ManualConnector()

    def fetch(
        self,
        source: SourceDefinition,
        *,
        limit: int | None = None,
        query: str | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        source_type = SourceType(source.source_type)
        connector = self._connector_for(source_type)
        infra_source = _infra_source(source)
        if source_type in {SourceType.RSS, SourceType.ATOM, SourceType.OFFICIAL_BLOG}:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.ARXIV:
            return connector.fetch(infra_source, query=query, limit=limit)
        if source_type == SourceType.GITHUB:
            return connector.fetch(infra_source, query=query, limit=limit)
        if source_type == SourceType.HACKERNEWS:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.REDDIT:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.LOBSTERS:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.STACKOVERFLOW:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.DEVTO:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.MEDIUM:
            return connector.fetch(infra_source, limit=limit)
        if source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            return connector.fetch(infra_source, limit=limit)
        if source_type == SourceType.MANUAL:
            return connector.fetch(infra_source, limit=limit)
        raise ValueError(f"unsupported source_type: {source_type.value}")

    def _connector_for(self, source_type: SourceType) -> Any:
        if source_type in {SourceType.RSS, SourceType.ATOM, SourceType.OFFICIAL_BLOG}:
            return self.feed_connector
        if source_type == SourceType.ARXIV:
            return self.arxiv_connector
        if source_type == SourceType.GITHUB:
            return self.github_connector
        if source_type == SourceType.HACKERNEWS:
            return self.hackernews_connector
        if source_type == SourceType.REDDIT:
            return self.reddit_connector
        if source_type == SourceType.LOBSTERS:
            return self.lobsters_connector
        if source_type == SourceType.STACKOVERFLOW:
            return self.stackoverflow_connector
        if source_type == SourceType.DEVTO:
            return self.devto_connector
        if source_type == SourceType.MEDIUM:
            return self.medium_connector
        if source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            return self.html_connector
        if source_type == SourceType.MANUAL:
            return self.manual_connector
        raise ValueError(f"unsupported source_type: {source_type.value}")


def _infra_source(source: SourceDefinition) -> InfraSourceDefinition:
    return InfraSourceDefinition(
        source_id=source.source_id,
        name=source.name,
        source_type=InfraSourceType(SourceType(source.source_type).value),
        url=source.url,
        reliability=InfraSourceReliability(source.reliability.value),
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
