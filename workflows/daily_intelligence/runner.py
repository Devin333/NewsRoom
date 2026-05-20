from __future__ import annotations

from pathlib import Path

from core.framework import RunResult, WorkflowRunner
from framework.llm import LLMClient
from core.framework.workflow import FunctionStepRegistry
from business.layers.relation.lineage import evidence_bundle_lineage_extractor
from business.layers.signal.indexing import source_artifact_ref_extractor
from sources import SourceRegistry
from sources.connectors import (
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
from sources.health import BasicSourceHealthManager
from workflows.daily_intelligence.profiles import (
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    validate_daily_profile,
)
from workflows.daily_intelligence.artifact_publisher import DailyIntelligenceArtifactPublisher
from workflows.daily_intelligence.registry import build_daily_intelligence_registry
from workflows.daily_intelligence.report_writer import ReportWriter
from workflows.daily_intelligence.source_collection import DailySourceCollector
from workflows.daily_intelligence.source_config import (
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from workflows.daily_intelligence.spec import (
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    build_daily_intelligence_workflow,
)
from workflows.daily_intelligence.source_processing import AllSourcesFailedError


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
        self.report_writer = ReportWriter(llm_client=self.llm_client)

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
        )
        return runner.run(
            build_daily_intelligence_workflow(profile),
            {"topic": topic, "source_limit": source_limit, "profile": profile},
            profile=profile,
            run_id=run_id,
        )

