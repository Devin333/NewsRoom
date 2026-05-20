from __future__ import annotations

from pathlib import Path
from typing import Any

from framework import RunResult, WorkflowRunner
from framework.llm import LLMClient
from framework.workflow import FunctionStepRegistry
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
from business.boards.cross_board.workflows.daily_intelligence.agent_registry import (
    build_daily_agent_registry,
    build_daily_agent_runner,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import DailyIntelligenceArtifactPublisher
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import build_evidence
from business.boards.cross_board.workflows.daily_intelligence.finalize_report_step import finalize_report
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE_OFFLINE,
    validate_daily_profile,
)
from business.boards.cross_board.workflows.daily_intelligence.source_collection import DailySourceCollector
from business.boards.cross_board.workflows.daily_intelligence.source_config import (
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher
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
        self.artifact_root = Path(artifact_root)
        self.source_registry = source_registry or build_default_source_registry(
            source_config_path=source_config_path
        )
        default_fetch_policy = build_default_source_fetch_policy(
            source_config_path=source_config_path
        )
        default_rate_limiter = source_rate_limiter or DomainRateLimiter()
        self.feed_connector = feed_connector or FeedConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.html_connector = html_connector or HtmlConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.manual_connector = manual_connector or ManualConnector()
        self.arxiv_connector = arxiv_connector or ArxivConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.github_connector = github_connector or GithubConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.hackernews_connector = hackernews_connector or HackerNewsConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.reddit_connector = reddit_connector or RedditConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.lobsters_connector = lobsters_connector or LobstersConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.stackoverflow_connector = stackoverflow_connector or StackOverflowConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.devto_connector = devto_connector or DevToConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.medium_connector = medium_connector or MediumConnector(
            feed_connector=FeedConnector(
                fetch_policy=default_fetch_policy,
                rate_limiter=default_rate_limiter,
            )
        )
        self.llm_client = llm_client
        self.source_health_manager = source_health_manager or BasicSourceHealthManager()
        self.source_dispatcher = SourceDispatcher(
            source_registry=self.source_registry,
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
        self.source_collector = DailySourceCollector(
            source_registry=self.source_registry,
            source_dispatcher=self.source_dispatcher,
            source_health_manager=self.source_health_manager,
        )

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
        registry.register("daily.finalize_report", finalize_report)
        return registry

    def run(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int = 3,
        run_id: str | None = None,
    ) -> RunResult:
        validate_daily_profile(profile)
        function_registry = self._function_registry(profile)
        tool_registry = build_daily_agent_tool_registry()
        agent_registry = build_daily_agent_registry()
        agent_runner = build_daily_agent_runner(
            profile=profile,
            llm_client=self.llm_client,
            topic=topic,
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

