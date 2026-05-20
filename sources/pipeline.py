from __future__ import annotations

from pathlib import Path
from typing import Any

from framework import RunResult
from framework.llm import LLMClient
from infrastructure.external.source_adapters import (
    DomainRateLimiter,
    FeedConnector,
    HtmlConnector,
    ManualConnector,
    SourceConfigError,
    SourceFetchPolicy,
    SourceRegistry,
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from sources.connectors import (
    ArxivConnector,
    DevToConnector,
    GithubConnector,
    HackerNewsConnector,
    LobstersConnector,
    MediumConnector,
    RedditConnector,
    StackOverflowConnector,
)
from sources.health import BasicSourceHealthManager
from workflows.daily_intelligence.runner import (
    AllSourcesFailedError,
    DailyIntelligenceRunner as _DailyIntelligenceRunner,
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    build_daily_intelligence_workflow,
)


class DailyIntelligenceRunner:
    """Legacy source-pipeline runner adapter.

    TODO(boundary-migration): remove this module after callers use business board
    services or `workflows.daily_intelligence.runner` directly.
    """

    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
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
        llm_client: LLMClient | None = None,
        source_health_manager: BasicSourceHealthManager | None = None,
        source_config_path: str | Path | None = None,
        source_rate_limiter: DomainRateLimiter | None = None,
    ) -> None:
        self._runner = _DailyIntelligenceRunner(
            artifact_root=artifact_root,
            source_registry=source_registry,
            feed_connector=feed_connector,
            html_connector=html_connector,
            manual_connector=manual_connector,
            arxiv_connector=arxiv_connector,
            github_connector=github_connector,
            hackernews_connector=hackernews_connector,
            reddit_connector=reddit_connector,
            lobsters_connector=lobsters_connector,
            stackoverflow_connector=stackoverflow_connector,
            devto_connector=devto_connector,
            medium_connector=medium_connector,
            llm_client=llm_client,
            source_health_manager=source_health_manager,
            source_config_path=source_config_path,
            source_rate_limiter=source_rate_limiter,
        )

    def run(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int = 3,
        run_id: str | None = None,
    ) -> RunResult:
        return self._runner.run(
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runner, name)


__all__ = [
    "AllSourcesFailedError",
    "DailyIntelligenceRunner",
    "PROFILE_LIVE",
    "PROFILE_LIVE_OFFLINE",
    "WORKFLOW_ID",
    "WORKFLOW_VERSION",
    "SourceConfigError",
    "SourceFetchPolicy",
    "SourceRegistry",
    "build_daily_intelligence_workflow",
    "build_default_source_fetch_policy",
    "build_default_source_registry",
]

