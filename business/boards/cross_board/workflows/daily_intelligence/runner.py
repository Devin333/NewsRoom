from __future__ import annotations

from pathlib import Path

from framework import RunResult, WorkflowRunner
from framework.llm import LLMClient
from framework.workflow import FunctionStepRegistry
from framework.workflow.routing import RoutingEngine
from business.memory.intelligence_recall import IntelligenceMemoryRecallService
from business.layers.relation.lineage import evidence_bundle_lineage_extractor
from business.layers.signal.indexing import source_artifact_ref_extractor
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import DailyIntelligenceRuntime
from business.boards.cross_board.workflows.daily_intelligence.runtime_assembly import (
    DailySourceRuntimeAssembly,
    build_daily_intelligence_runtime,
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
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    validate_daily_profile,
)
from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import DailyIntelligenceArtifactPublisher
from business.boards.cross_board.workflows.daily_intelligence.registry import build_daily_intelligence_registry
from business.boards.cross_board.workflows.daily_intelligence.routing_predicates import (
    build_daily_intelligence_routing_predicate_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.source_config import (
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.spec import (
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    build_daily_intelligence_workflow,
)
from business.boards.cross_board.workflows.daily_intelligence.source_processing import AllSourcesFailedError


__all__ = [
    "AllSourcesFailedError",
    "DailyIntelligenceRunner",
    "PROFILE_LIVE",
    "PROFILE_LIVE_OFFLINE",
    "WORKFLOW_ID",
    "WORKFLOW_VERSION",
    "build_daily_intelligence_registry",
    "build_daily_intelligence_workflow",
    "build_default_source_fetch_policy",
    "build_default_source_registry",
]


class DailyIntelligenceRunner:
    def __init__(
        self,
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
        source_health_manager: BasicSourceHealthManager | None = None,
        source_config_path: str | Path | None = None,
        source_rate_limiter: DailySourceRateLimiter | None = None,
        runtime: DailyIntelligenceRuntime | None = None,
    ) -> None:
        self.runtime = runtime or build_daily_intelligence_runtime(
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
            recall_service=recall_service,
            source_health_manager=source_health_manager,
            source_config_path=source_config_path,
            source_rate_limiter=source_rate_limiter,
        )
        self.artifact_root = self.runtime.artifact_root
        self.source_registry = self.runtime.source_registry
        self.source_dispatcher = self.runtime.source_dispatcher
        self.source_collector = self.runtime.source_collector
        self.source_health_manager = self.runtime.source_health_manager
        self.llm_client = self.runtime.llm_client
        self.recall_service = self.runtime.recall_service
        self.report_writer = self.runtime.report_writer
        self.source_runtime_assembly = DailySourceRuntimeAssembly(
            source_registry=self.source_registry,
            feed_connector=self.source_dispatcher.feed_connector,
            html_connector=self.source_dispatcher.html_connector,
            manual_connector=self.source_dispatcher.manual_connector,
            arxiv_connector=self.source_dispatcher.arxiv_connector,
            github_connector=self.source_dispatcher.github_connector,
            hackernews_connector=self.source_dispatcher.hackernews_connector,
            reddit_connector=self.source_dispatcher.reddit_connector,
            lobsters_connector=self.source_dispatcher.lobsters_connector,
            stackoverflow_connector=self.source_dispatcher.stackoverflow_connector,
            devto_connector=self.source_dispatcher.devto_connector,
            medium_connector=self.source_dispatcher.medium_connector,
            source_health_manager=self.source_health_manager,
            source_dispatcher=self.source_dispatcher,
            source_collector=self.source_collector,
        )

    @property
    def feed_connector(self) -> DailyFeedSourceConnector:
        return self.source_runtime_assembly.feed_connector

    @property
    def html_connector(self) -> DailyHtmlSourceConnector:
        return self.source_runtime_assembly.html_connector

    @property
    def manual_connector(self) -> DailyManualSourceConnector:
        return self.source_runtime_assembly.manual_connector

    @property
    def arxiv_connector(self) -> DailyArxivSourceConnector:
        return self.source_runtime_assembly.arxiv_connector

    @property
    def github_connector(self) -> DailyGithubSourceConnector:
        return self.source_runtime_assembly.github_connector

    @property
    def hackernews_connector(self) -> DailyHackerNewsSourceConnector:
        return self.source_runtime_assembly.hackernews_connector

    @property
    def reddit_connector(self) -> DailyRedditSourceConnector:
        return self.source_runtime_assembly.reddit_connector

    @property
    def lobsters_connector(self) -> DailyLobstersSourceConnector:
        return self.source_runtime_assembly.lobsters_connector

    @property
    def stackoverflow_connector(self) -> DailyStackOverflowSourceConnector:
        return self.source_runtime_assembly.stackoverflow_connector

    @property
    def devto_connector(self) -> DailyDevToSourceConnector:
        return self.source_runtime_assembly.devto_connector

    @property
    def medium_connector(self) -> DailyMediumSourceConnector:
        return self.source_runtime_assembly.medium_connector

    def _function_registry(self, profile: str) -> FunctionStepRegistry:
        return build_daily_intelligence_registry(
            profile=profile,
            collect_sources=self.source_collector.collect_sources,
            draft_report=self.report_writer.draft_report,
            memory_query_repository=(
                self.recall_service.repository if self.recall_service is not None else None
            ),
        )

    def run(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int = 3,
        run_id: str | None = None,
    ) -> RunResult:
        validate_daily_profile(profile)
        registry = self._function_registry(profile)
        runner = WorkflowRunner(
            artifact_root=self.artifact_root,
            function_registry=registry,
            artifact_publishers=[DailyIntelligenceArtifactPublisher()],
            artifact_ref_extractors=[source_artifact_ref_extractor],
            lineage_extractors=[evidence_bundle_lineage_extractor],
            routing_engine=RoutingEngine(
                predicate_registry=build_daily_intelligence_routing_predicate_registry()
            ),
        )
        return runner.run(
            build_daily_intelligence_workflow(profile),
            {"topic": topic, "source_limit": source_limit, "profile": profile},
            profile=profile,
            run_id=run_id,
        )

