from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceDefinition, SourceType


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
        fetch_policy: Any | None = None,
        rate_limiter: Any | None = None,
    ) -> None:
        self.fetch_policy = fetch_policy
        self.rate_limiter = rate_limiter
        self.feed_connector = feed_connector
        self.arxiv_connector = arxiv_connector
        self.github_connector = github_connector
        self.hackernews_connector = hackernews_connector
        self.reddit_connector = reddit_connector
        self.lobsters_connector = lobsters_connector
        self.stackoverflow_connector = stackoverflow_connector
        self.devto_connector = devto_connector
        self.medium_connector = medium_connector
        self.html_connector = html_connector
        self.manual_connector = manual_connector

    def fetch(
        self,
        source: SourceDefinition,
        *,
        limit: int | None = None,
        query: str | None = None,
    ) -> tuple[list[Any], list[Any]]:
        source_type = SourceType(source.source_type)
        connector = self._connector_for(source_type)
        if connector is None:
            raise ValueError(f"source connector is not configured for source_type: {source_type.value}")
        if source_type in {SourceType.RSS, SourceType.ATOM, SourceType.OFFICIAL_BLOG}:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.ARXIV:
            return connector.fetch(source, query=query, limit=limit)
        if source_type == SourceType.GITHUB:
            return connector.fetch(source, query=query, limit=limit)
        if source_type == SourceType.HACKERNEWS:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.REDDIT:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.LOBSTERS:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.STACKOVERFLOW:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.DEVTO:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.MEDIUM:
            return connector.fetch(source, limit=limit)
        if source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            return connector.fetch(source, limit=limit)
        if source_type == SourceType.MANUAL:
            return connector.fetch(source, limit=limit)
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
