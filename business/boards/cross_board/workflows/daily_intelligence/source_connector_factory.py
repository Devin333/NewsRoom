from __future__ import annotations

from pathlib import Path

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
    StackOverflowConnector,
)

from business.boards.cross_board.workflows.daily_intelligence.source_config import (
    build_default_source_fetch_policy,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_bundle import (
    DailySourceConnectorBundle,
)


def build_daily_source_connector_bundle(
    *,
    feed_connector: FeedConnector | None = None,
    html_connector: HtmlConnector | None = None,
    manual_connector: ManualConnector | None = None,
    arxiv_connector: ArxivConnector | None = None,
    github_connector: GithubConnector | None = None,
    hackernews_connector: HackerNewsConnector | None = None,
    reddit_connector: RedditConnector | None = None,
    lobsters_connector: LobstersConnector | None = None,
    stackoverflow_connector: StackOverflowConnector | None = None,
    devto_connector: DevToConnector | None = None,
    medium_connector: MediumConnector | None = None,
    source_config_path: str | Path | None = None,
    source_rate_limiter: DomainRateLimiter | None = None,
) -> DailySourceConnectorBundle:
    default_fetch_policy = build_default_source_fetch_policy(
        source_config_path=source_config_path
    )
    default_rate_limiter = source_rate_limiter or DomainRateLimiter()
    resolved_feed_connector = feed_connector or FeedConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_html_connector = html_connector or HtmlConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_manual_connector = manual_connector or ManualConnector()
    resolved_arxiv_connector = arxiv_connector or ArxivConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_github_connector = github_connector or GithubConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_hackernews_connector = hackernews_connector or HackerNewsConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_reddit_connector = reddit_connector or RedditConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_lobsters_connector = lobsters_connector or LobstersConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_stackoverflow_connector = stackoverflow_connector or StackOverflowConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_devto_connector = devto_connector or DevToConnector(
        fetch_policy=default_fetch_policy,
        rate_limiter=default_rate_limiter,
    )
    resolved_medium_connector = medium_connector or MediumConnector(
        feed_connector=FeedConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
    )
    return DailySourceConnectorBundle(
        feed_connector=resolved_feed_connector,
        html_connector=resolved_html_connector,
        manual_connector=resolved_manual_connector,
        arxiv_connector=resolved_arxiv_connector,
        github_connector=resolved_github_connector,
        hackernews_connector=resolved_hackernews_connector,
        reddit_connector=resolved_reddit_connector,
        lobsters_connector=resolved_lobsters_connector,
        stackoverflow_connector=resolved_stackoverflow_connector,
        devto_connector=resolved_devto_connector,
        medium_connector=resolved_medium_connector,
    )


__all__ = ["build_daily_source_connector_bundle"]
