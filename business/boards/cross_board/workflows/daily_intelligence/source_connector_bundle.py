from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class DailySourceConnectorBundle:
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
