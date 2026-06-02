from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.memory.intelligence_recall import IntelligenceMemoryRecallService
from framework.llm import LLMClient
from business.layers.signal.source_config import build_default_source_registry

from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import (
    DailyIntelligenceRuntime,
)
from business.boards.cross_board.workflows.daily_intelligence.report_writer import ReportWriter
from business.boards.cross_board.workflows.daily_intelligence.source_collection import DailySourceCollector
from business.boards.cross_board.workflows.daily_intelligence.source_connector_bundle import (
    DailySourceConnectorBundle,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_factory import (
    build_daily_source_connector_bundle,
)
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
    DailySourceRateLimiter,
    DailyStackOverflowSourceConnector,
)
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher


@dataclass(frozen=True)
class DailySourceRuntimeAssembly:
    source_registry: SourceRegistry
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
    source_health_manager: BasicSourceHealthManager
    source_dispatcher: SourceDispatcher
    source_collector: DailySourceCollector

    @property
    def connector_bundle(self) -> DailySourceConnectorBundle:
        return DailySourceConnectorBundle(
            feed_connector=self.feed_connector,
            html_connector=self.html_connector,
            manual_connector=self.manual_connector,
            arxiv_connector=self.arxiv_connector,
            github_connector=self.github_connector,
            hackernews_connector=self.hackernews_connector,
            reddit_connector=self.reddit_connector,
            lobsters_connector=self.lobsters_connector,
            stackoverflow_connector=self.stackoverflow_connector,
            devto_connector=self.devto_connector,
            medium_connector=self.medium_connector,
        )


def build_daily_intelligence_runtime(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    source_registry: SourceRegistry | None = None,
    feed_connector: DailyFeedSourceConnector | None = None,
    html_connector: DailyHtmlSourceConnector | None = None,
    manual_connector: DailyManualSourceConnector | None = None,
    arxiv_connector: DailyArxivSourceConnector | None = None,
    github_connector: DailyGithubSourceConnector | None = None,
    hackernews_connector: DailyHackerNewsSourceConnector | None = None,
    reddit_connector: DailyRedditSourceConnector | None = None,
    lobsters_connector: DailyLobstersSourceConnector | None = None,
    stackoverflow_connector: DailyStackOverflowSourceConnector | None = None,
    devto_connector: DailyDevToSourceConnector | None = None,
    medium_connector: DailyMediumSourceConnector | None = None,
    llm_client: LLMClient | None = None,
    recall_service: IntelligenceMemoryRecallService | None = None,
    report_writer: ReportWriter | None = None,
    source_health_manager: BasicSourceHealthManager | None = None,
    source_config_path: str | Path | None = None,
    source_rate_limiter: DailySourceRateLimiter | None = None,
) -> DailyIntelligenceRuntime:
    source_assembly = build_daily_source_runtime_assembly(
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
        source_health_manager=source_health_manager,
        source_config_path=source_config_path,
        source_rate_limiter=source_rate_limiter,
    )
    resolved_report_writer = report_writer or ReportWriter(
        llm_client=llm_client,
        recall_service=recall_service,
    )
    return DailyIntelligenceRuntime(
        artifact_root=Path(artifact_root),
        source_registry=source_assembly.source_registry,
        source_dispatcher=source_assembly.source_dispatcher,
        source_collector=source_assembly.source_collector,
        report_writer=resolved_report_writer,
        source_health_manager=source_assembly.source_health_manager,
        recall_service=recall_service,
        llm_client=llm_client,
    )


def source_runtime_assembly_from_runtime(
    runtime: DailyIntelligenceRuntime,
) -> DailySourceRuntimeAssembly:
    dispatcher = runtime.source_dispatcher
    return DailySourceRuntimeAssembly(
        source_registry=runtime.source_registry,
        feed_connector=dispatcher.feed_connector,
        html_connector=dispatcher.html_connector,
        manual_connector=dispatcher.manual_connector,
        arxiv_connector=dispatcher.arxiv_connector,
        github_connector=dispatcher.github_connector,
        hackernews_connector=dispatcher.hackernews_connector,
        reddit_connector=dispatcher.reddit_connector,
        lobsters_connector=dispatcher.lobsters_connector,
        stackoverflow_connector=dispatcher.stackoverflow_connector,
        devto_connector=dispatcher.devto_connector,
        medium_connector=dispatcher.medium_connector,
        source_health_manager=runtime.source_health_manager,
        source_dispatcher=runtime.source_dispatcher,
        source_collector=runtime.source_collector,
    )


def build_daily_source_runtime_assembly(
    *,
    source_registry: SourceRegistry | None = None,
    feed_connector: DailyFeedSourceConnector | None = None,
    html_connector: DailyHtmlSourceConnector | None = None,
    manual_connector: DailyManualSourceConnector | None = None,
    arxiv_connector: DailyArxivSourceConnector | None = None,
    github_connector: DailyGithubSourceConnector | None = None,
    hackernews_connector: DailyHackerNewsSourceConnector | None = None,
    reddit_connector: DailyRedditSourceConnector | None = None,
    lobsters_connector: DailyLobstersSourceConnector | None = None,
    stackoverflow_connector: DailyStackOverflowSourceConnector | None = None,
    devto_connector: DailyDevToSourceConnector | None = None,
    medium_connector: DailyMediumSourceConnector | None = None,
    source_health_manager: BasicSourceHealthManager | None = None,
    source_config_path: str | Path | None = None,
    source_rate_limiter: DailySourceRateLimiter | None = None,
) -> DailySourceRuntimeAssembly:
    resolved_source_registry = source_registry or build_default_source_registry(
        source_config_path=source_config_path
    )
    connector_bundle = build_daily_source_connector_bundle(
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
        source_config_path=source_config_path,
        source_rate_limiter=source_rate_limiter,
    )
    resolved_source_health_manager = source_health_manager or BasicSourceHealthManager()
    source_dispatcher = SourceDispatcher(
        source_registry=resolved_source_registry,
        feed_connector=connector_bundle.feed_connector,
        html_connector=connector_bundle.html_connector,
        manual_connector=connector_bundle.manual_connector,
        arxiv_connector=connector_bundle.arxiv_connector,
        github_connector=connector_bundle.github_connector,
        hackernews_connector=connector_bundle.hackernews_connector,
        reddit_connector=connector_bundle.reddit_connector,
        lobsters_connector=connector_bundle.lobsters_connector,
        stackoverflow_connector=connector_bundle.stackoverflow_connector,
        devto_connector=connector_bundle.devto_connector,
        medium_connector=connector_bundle.medium_connector,
    )
    source_collector = DailySourceCollector(
        source_registry=resolved_source_registry,
        source_dispatcher=source_dispatcher,
        source_health_manager=resolved_source_health_manager,
    )
    return DailySourceRuntimeAssembly(
        source_registry=resolved_source_registry,
        feed_connector=connector_bundle.feed_connector,
        html_connector=connector_bundle.html_connector,
        manual_connector=connector_bundle.manual_connector,
        arxiv_connector=connector_bundle.arxiv_connector,
        github_connector=connector_bundle.github_connector,
        hackernews_connector=connector_bundle.hackernews_connector,
        reddit_connector=connector_bundle.reddit_connector,
        lobsters_connector=connector_bundle.lobsters_connector,
        stackoverflow_connector=connector_bundle.stackoverflow_connector,
        devto_connector=connector_bundle.devto_connector,
        medium_connector=connector_bundle.medium_connector,
        source_health_manager=resolved_source_health_manager,
        source_dispatcher=source_dispatcher,
        source_collector=source_collector,
    )


__all__ = [
    "DailyIntelligenceRuntime",
    "DailySourceRuntimeAssembly",
    "build_daily_intelligence_runtime",
    "build_daily_source_runtime_assembly",
    "source_runtime_assembly_from_runtime",
]
