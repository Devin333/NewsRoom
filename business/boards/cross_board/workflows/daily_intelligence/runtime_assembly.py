from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.memory.intelligence_recall import IntelligenceMemoryRecallService
from framework.llm import LLMClient

from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import (
    DailyIntelligenceRuntime,
)
from business.boards.cross_board.workflows.daily_intelligence.report_writer import ReportWriter
from business.boards.cross_board.workflows.daily_intelligence.source_collection import DailySourceCollector
from business.boards.cross_board.workflows.daily_intelligence.source_config import (
    build_default_source_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_bundle import (
    CONNECTOR_FIELD_NAMES,
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
            **{field_name: getattr(self, field_name) for field_name in CONNECTOR_FIELD_NAMES}
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
        **{field_name: getattr(connector_bundle, field_name) for field_name in CONNECTOR_FIELD_NAMES},
    )
    source_collector = DailySourceCollector(
        source_registry=resolved_source_registry,
        source_dispatcher=source_dispatcher,
        source_health_manager=resolved_source_health_manager,
    )
    return DailySourceRuntimeAssembly(
        source_registry=resolved_source_registry,
        **{field_name: getattr(connector_bundle, field_name) for field_name in CONNECTOR_FIELD_NAMES},
        source_health_manager=resolved_source_health_manager,
        source_dispatcher=source_dispatcher,
        source_collector=source_collector,
    )


def apply_daily_source_runtime_assembly(owner: object, assembly: DailySourceRuntimeAssembly) -> None:
    for field_name in (
        "source_registry",
        *CONNECTOR_FIELD_NAMES,
        "source_health_manager",
        "source_dispatcher",
        "source_collector",
    ):
        setattr(owner, field_name, getattr(assembly, field_name))


__all__ = [
    "DailyIntelligenceRuntime",
    "DailySourceRuntimeAssembly",
    "apply_daily_source_runtime_assembly",
    "build_daily_intelligence_runtime",
    "build_daily_source_runtime_assembly",
]
