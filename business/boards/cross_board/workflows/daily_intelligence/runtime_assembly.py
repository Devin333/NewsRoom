from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
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

from business.boards.cross_board.workflows.daily_intelligence.source_collection import DailySourceCollector
from business.boards.cross_board.workflows.daily_intelligence.source_config import (
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher


@dataclass(frozen=True)
class DailySourceRuntimeAssembly:
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
    source_health_manager: BasicSourceHealthManager
    source_dispatcher: SourceDispatcher
    source_collector: DailySourceCollector


def build_daily_source_runtime_assembly(
    *,
    source_registry: SourceRegistry | None = None,
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
    source_health_manager: BasicSourceHealthManager | None = None,
    source_config_path: str | Path | None = None,
    source_rate_limiter: DomainRateLimiter | None = None,
) -> DailySourceRuntimeAssembly:
    resolved_source_registry = source_registry or build_default_source_registry(
        source_config_path=source_config_path
    )
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
    resolved_source_health_manager = source_health_manager or BasicSourceHealthManager()
    source_dispatcher = SourceDispatcher(
        source_registry=resolved_source_registry,
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
    source_collector = DailySourceCollector(
        source_registry=resolved_source_registry,
        source_dispatcher=source_dispatcher,
        source_health_manager=resolved_source_health_manager,
    )
    return DailySourceRuntimeAssembly(
        source_registry=resolved_source_registry,
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
        source_health_manager=resolved_source_health_manager,
        source_dispatcher=source_dispatcher,
        source_collector=source_collector,
    )


def apply_daily_source_runtime_assembly(owner: object, assembly: DailySourceRuntimeAssembly) -> None:
    for field_name in (
        "source_registry",
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
        "source_health_manager",
        "source_dispatcher",
        "source_collector",
    ):
        setattr(owner, field_name, getattr(assembly, field_name))


__all__ = [
    "DailySourceRuntimeAssembly",
    "apply_daily_source_runtime_assembly",
    "build_daily_source_runtime_assembly",
]
