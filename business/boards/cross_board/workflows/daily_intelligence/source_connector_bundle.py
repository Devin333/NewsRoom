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


__all__ = ["DailySourceConnectorBundle"]
