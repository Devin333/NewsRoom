from __future__ import annotations

from pathlib import Path

from framework import RunResult, WorkflowRunner
from framework.llm import LLMClient
from framework.workflow import FunctionStepRegistry
from framework.workflow.routing import RoutingEngine
from business.layers.relation.lineage import evidence_bundle_lineage_extractor
from business.layers.signal.indexing import source_artifact_ref_extractor
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import (
    DailyIntelligenceRuntime,
)
from business.boards.cross_board.workflows.daily_intelligence.runtime_assembly import (
    build_daily_intelligence_runtime,
    source_runtime_assembly_from_runtime,
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
from business.boards.cross_board.workflows.daily_intelligence.source_collection import DailySourceCollector
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from business.boards.cross_board.workflows.daily_intelligence.agent_registry import (
    build_daily_agent_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_runner_factory import (
    build_profiled_daily_agent_runner,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback import collect_agent_feedback
from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import DailyIntelligenceArtifactPublisher
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import build_evidence
from business.boards.cross_board.workflows.daily_intelligence.finalize_report_step import finalize_report
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE_OFFLINE,
    validate_daily_profile,
)
from business.boards.cross_board.workflows.daily_intelligence.routing_predicates import (
    build_daily_intelligence_routing_predicate_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.source_processing import (
    AllSourcesFailedError,
    deduplicate_sources,
    normalize_sources,
    rank_sources,
    require_sources,
)
from business.boards.cross_board.workflows.daily_intelligence.spec_agentic import (
    AGENTIC_WORKFLOW_ID,
    AGENTIC_WORKFLOW_VERSION,
    build_agentic_daily_intelligence_workflow,
)


__all__ = [
    "AGENTIC_WORKFLOW_ID",
    "AGENTIC_WORKFLOW_VERSION",
    "AgenticDailyIntelligenceRunner",
    "AllSourcesFailedError",
    "PROFILE_AGENTIC_OFFLINE",
    "build_agentic_daily_intelligence_workflow",
]


class AgenticDailyIntelligenceRunner:
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
            source_health_manager=source_health_manager,
            source_config_path=source_config_path,
            source_rate_limiter=source_rate_limiter,
        )
        self.artifact_root = self.runtime.artifact_root
        self.source_runtime_assembly = source_runtime_assembly_from_runtime(self.runtime)
        self.source_collector: DailySourceCollector = self.runtime.source_collector
        self.llm_client = self.runtime.llm_client

    @property
    def source_registry(self) -> SourceRegistry:
        return self.source_runtime_assembly.source_registry

    @property
    def source_health_manager(self) -> BasicSourceHealthManager:
        return self.source_runtime_assembly.source_health_manager

    @property
    def source_dispatcher(self) -> SourceDispatcher:
        return self.source_runtime_assembly.source_dispatcher

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
        validate_daily_profile(profile)
        registry = FunctionStepRegistry()
        registry.register(
            "daily.collect_sources",
            lambda buffer: self.source_collector.collect_sources(
                buffer,
                _source_collection_profile(profile),
            ),
        )
        registry.register("daily.require_sources", require_sources)
        registry.register("daily.normalize_sources", normalize_sources)
        registry.register("daily.deduplicate_sources", deduplicate_sources)
        registry.register("daily.rank_sources", rank_sources)
        registry.register("daily.build_evidence", build_evidence)
        registry.register("daily.collect_agent_feedback", collect_agent_feedback)
        registry.register("daily.finalize_report", finalize_report)
        return registry

    def run(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int = 3,
        run_id: str | None = None,
        agent_fixture_scenario: str | None = None,
    ) -> RunResult:
        validate_daily_profile(profile)
        function_registry = self._function_registry(profile)
        tool_registry = build_daily_agent_tool_registry()
        agent_registry = build_daily_agent_registry()
        agent_runner = build_profiled_daily_agent_runner(
            profile=profile,
            llm_client=self.llm_client,
            topic=topic,
            fixture_scenario=agent_fixture_scenario,
        )
        runner = WorkflowRunner(
            artifact_root=self.artifact_root,
            function_registry=function_registry,
            tool_registry=tool_registry,
            agent_runner=agent_runner,
            agent_registry=agent_registry,
            artifact_publishers=[DailyIntelligenceArtifactPublisher()],
            artifact_ref_extractors=[source_artifact_ref_extractor],
            lineage_extractors=[evidence_bundle_lineage_extractor],
            routing_engine=RoutingEngine(
                predicate_registry=build_daily_intelligence_routing_predicate_registry()
            ),
        )
        return runner.run(
            build_agentic_daily_intelligence_workflow(profile),
            {"topic": topic, "source_limit": source_limit, "profile": profile},
            profile=profile,
            run_id=run_id,
        )


def _source_collection_profile(profile: str) -> str:
    if profile == PROFILE_AGENTIC_OFFLINE:
        return PROFILE_LIVE_OFFLINE
    return profile

