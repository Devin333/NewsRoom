from __future__ import annotations

from dataclasses import dataclass

from infrastructure.external.sources import (
    ArxivConnector,
    DevToConnector,
    FeedConnector,
    GithubConnector,
    HackerNewsConnector,
    HtmlConnector,
    LobstersConnector,
    ManualConnector,
    MediumConnector,
    RedditConnector,
    StackOverflowConnector,
)


@dataclass(frozen=True)
class DailySourceConnectorBundle:
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


CONNECTOR_FIELD_NAMES = (
    "feed_connector",
    "html_connector",
    "manual_connector",
    "arxiv_connector",
    "github_connector",
    "hackernews_connector",
    "reddit_connector",
    "lobsters_connector",
    "stackoverflow_connector",
    "devto_connector",
    "medium_connector",
)


__all__ = ["CONNECTOR_FIELD_NAMES", "DailySourceConnectorBundle"]
