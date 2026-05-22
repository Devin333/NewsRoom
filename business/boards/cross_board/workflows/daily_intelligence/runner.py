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
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import DailyIntelligenceRuntime
from business.boards.cross_board.workflows.daily_intelligence.runtime_assembly import (
    DailySourceRuntimeAssembly,
    build_daily_intelligence_runtime,
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
from business.boards.cross_board.workflows.daily_intelligence.source_connector_bundle import CONNECTOR_FIELD_NAMES
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
        recall_service: IntelligenceMemoryRecallService | None = None,
        source_health_manager: BasicSourceHealthManager | None = None,
        source_config_path: str | Path | None = None,
        source_rate_limiter: DomainRateLimiter | None = None,
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
        for field_name in CONNECTOR_FIELD_NAMES:
            setattr(self, field_name, getattr(self.source_dispatcher, field_name))
        self.source_runtime_assembly = DailySourceRuntimeAssembly(
            source_registry=self.source_registry,
            **{field_name: getattr(self, field_name) for field_name in CONNECTOR_FIELD_NAMES},
            source_health_manager=self.source_health_manager,
            source_dispatcher=self.source_dispatcher,
            source_collector=self.source_collector,
        )

    def _function_registry(self, profile: str) -> FunctionStepRegistry:
        return build_daily_intelligence_registry(
            profile=profile,
            collect_sources=self.source_collector.collect_sources,
            draft_report=self.report_writer.draft_report,
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

