from __future__ import annotations

from pathlib import Path

from business.boards.cross_board.profiles import (
    AGENTIC_DAILY_WORKFLOW_ID,
    LEGACY_DAILY_WORKFLOW_ID,
    PROFILE_AGENTIC_LIVE,
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    daily_agentic_enabled,
)
from framework import RunResult

from business.boards.cross_board.workflows.daily_intelligence import (
    AgenticDailyIntelligenceRunner,
    DailyIntelligenceRunner,
    build_agentic_daily_intelligence_workflow,
    build_daily_intelligence_workflow,
    build_test_agent_loop_registry,
    build_test_agent_loop_workflow,
    build_test_no_llm_registry,
    build_test_no_llm_workflow,
)
from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import (
    build_daily_intelligence_artifact_publishers,
)
from business.boards.cross_board.workflows.daily_intelligence.test_agent_loop import run_test_agent_loop
from business.boards.cross_board.workflows.daily_intelligence.test_no_llm import run_test_no_llm
from business.boards.cross_board.workflows.weekly_intelligence import (
    PROFILE_WEEKLY,
    WeeklyIntelligenceRunner,
)
from business.layers.memory.ingestion import MemoryIngestionService
from business.layers.relation.lineage import evidence_bundle_lineage_extractor
from business.layers.signal.indexing import source_artifact_ref_extractor
from interfaces.services.approval_resume_service import (
    DEFAULT_CHECKPOINT_STORE_PATH,
    ApprovalResumeApplicationService,
    ApprovalWorkflowResumeResult,
)
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.board_service import BoardApplicationService
from interfaces.services.daily_run_service import DailyRunApplicationService
from interfaces.services.diagnose_service import DiagnoseCheck, DiagnoseResult, DiagnosticApplicationService
from interfaces.services.live_smoke_service import (
    LiveSmokeApplicationService,
    LiveSmokeResult,
    LiveSmokeStatus,
    live_smoke_readiness_issues,
    readiness_message,
)
from interfaces.services.memory_service import memory_ingestion_service_from_env
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_persistence_service import RunPersistenceApplicationService
from interfaces.services.run_resolution_service import (
    ResolvedWorkflow,
    RunResolutionApplicationService,
    normalize_profile,
    normalize_workflow_id,
)
from interfaces.services.weekly_run_service import WeeklyRunApplicationService
from infrastructure.storage.repository import persist_run_result, repository_from_env


_ResolvedWorkflow = ResolvedWorkflow
_live_smoke_readiness_issues = live_smoke_readiness_issues
_readiness_message = readiness_message
_normalize_workflow_id = normalize_workflow_id
_normalize_profile = normalize_profile


class RunApplicationService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        memory_ingestion_service: MemoryIngestionService | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.memory_ingestion_service = memory_ingestion_service

    def run_test_no_llm(self, *, topic: str, run_id: str | None = None) -> RunResult:
        return self._daily_service().run_test_no_llm(topic=topic, run_id=run_id)

    def run_test_agent_loop(self, *, topic: str, run_id: str | None = None) -> RunResult:
        return self._daily_service().run_test_agent_loop(topic=topic, run_id=run_id)

    def run_daily(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None = None,
    ) -> RunResult:
        return self._daily_service().run_daily(
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )

    def run_daily_agentic(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None = None,
    ) -> RunResult:
        return self._daily_service().run_daily_agentic(
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )

    def run_live_smoke(
        self,
        *,
        topic: str = "AI",
        source_limit: int = 3,
        run_id: str | None = None,
        skip_if_unready: bool = True,
    ) -> LiveSmokeResult:
        return LiveSmokeApplicationService(
            diagnostic_service_factory=DiagnosticApplicationService,
            run_daily_agentic=self.run_daily_agentic,
            live_profile=PROFILE_AGENTIC_LIVE,
        ).run_live_smoke(
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
            skip_if_unready=skip_if_unready,
        )

    def run_weekly(
        self,
        *,
        language: str = "en",
        topic: str | None = None,
        source_limit: int = 20,
        period_start: str | None = None,
        period_end: str | None = None,
        run_id: str | None = None,
    ) -> RunResult:
        return WeeklyRunApplicationService(
            artifact_root=self.artifact_root,
            persistence_service=self._persistence_service(),
            report_service_factory=ReportApplicationService,
            weekly_runner_cls=WeeklyIntelligenceRunner,
            profile=PROFILE_WEEKLY,
        ).run_weekly(
            language=language,
            topic=topic,
            source_limit=source_limit,
            period_start=period_start,
            period_end=period_end,
            run_id=run_id,
        )

    def resume_from_approval(
        self,
        approval_id: str,
        *,
        workflow_id: str = "daily",
        profile: str | None = None,
        run_id: str | None = None,
        decision_key: str = "human_review_decision",
        approval_service: ApprovalApplicationService | None = None,
        checkpoint_store_path: str | Path = DEFAULT_CHECKPOINT_STORE_PATH,
    ) -> ApprovalWorkflowResumeResult:
        return ApprovalResumeApplicationService(
            artifact_root=self.artifact_root,
            resolution_service=RunResolutionApplicationService(resolver=_resolve_approval_resume_workflow),
            artifact_publishers_factory=build_daily_intelligence_artifact_publishers,
            artifact_ref_extractors=[source_artifact_ref_extractor],
            lineage_extractors=[evidence_bundle_lineage_extractor],
        ).resume_from_approval(
            approval_id,
            workflow_id=workflow_id,
            profile=profile,
            run_id=run_id,
            decision_key=decision_key,
            approval_service=approval_service,
            checkpoint_store_path=checkpoint_store_path,
        )

    def resume_approval(self, approval_id: str, **kwargs) -> ApprovalWorkflowResumeResult:
        return self.resume_from_approval(approval_id, **kwargs)

    def _persistence_service(self) -> RunPersistenceApplicationService:
        return RunPersistenceApplicationService(
            artifact_root=self.artifact_root,
            repository_factory=repository_from_env,
            persist_result=persist_run_result,
        )

    def _daily_service(self) -> DailyRunApplicationService:
        return DailyRunApplicationService(
            artifact_root=self.artifact_root,
            persistence_service=self._persistence_service(),
            memory_ingestion_service=self.memory_ingestion_service,
            memory_ingestion_service_factory=memory_ingestion_service_from_env,
            board_service_factory=BoardApplicationService,
            runner_cls_resolver=_daily_runner_cls,
            agentic_runner_cls=AgenticDailyIntelligenceRunner,
            test_no_llm_runner=run_test_no_llm,
            test_agent_loop_runner=run_test_agent_loop,
        )

    def _index_memory_if_configured(self, result: RunResult, *, topic: str) -> None:
        self._daily_service()._index_memory_if_configured(result, topic=topic)

    def _run_daily_with_runner(
        self,
        *,
        runner_cls,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None,
    ) -> RunResult:
        return self._daily_service()._run_daily_with_runner(
            runner_cls=runner_cls,
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )

    def _attach_board_outputs_if_possible(self, result: RunResult, *, topic: str) -> None:
        self._daily_service()._attach_board_outputs_if_possible(result, topic=topic)


def _daily_runner_cls(profile: str):
    if profile in {PROFILE_LIVE, PROFILE_LIVE_OFFLINE}:
        return AgenticDailyIntelligenceRunner
    return AgenticDailyIntelligenceRunner if daily_agentic_enabled(profile) else DailyIntelligenceRunner


def _resolve_approval_resume_workflow(
    workflow_id: str,
    *,
    profile: str | None,
) -> ResolvedWorkflow:
    normalized_workflow = _normalize_workflow_id(workflow_id)
    normalized_profile = _normalize_profile(profile)
    if normalized_workflow in {
        "daily",
        "daily-intelligence",
        "daily_intelligence",
        LEGACY_DAILY_WORKFLOW_ID,
        AGENTIC_DAILY_WORKFLOW_ID,
    }:
        actual_profile = normalized_profile or PROFILE_AGENTIC_LIVE
        if actual_profile == PROFILE_LIVE:
            actual_profile = PROFILE_AGENTIC_LIVE
        if actual_profile == PROFILE_LIVE_OFFLINE:
            actual_profile = PROFILE_AGENTIC_OFFLINE
        if actual_profile not in {PROFILE_AGENTIC_LIVE, PROFILE_AGENTIC_OFFLINE}:
            raise ValueError(
                f"unsupported daily approval resume profile: {actual_profile}"
            )
        runner = AgenticDailyIntelligenceRunner()
        return ResolvedWorkflow(
            workflow=build_agentic_daily_intelligence_workflow(actual_profile),
            profile=actual_profile,
            registry=runner._function_registry(actual_profile),
        )
    if normalized_workflow in {"test-no-llm", "daily-intelligence-test-no-llm"}:
        if normalized_profile and normalized_profile != "test-no-llm":
            raise ValueError(
                f"unsupported test-no-llm approval resume profile: {normalized_profile}"
            )
        return ResolvedWorkflow(
            workflow=build_test_no_llm_workflow(),
            profile="test-no-llm",
            registry=build_test_no_llm_registry(),
        )
    if normalized_workflow in {"test-agent-loop", "daily-intelligence-test-agent-loop"}:
        if normalized_profile and normalized_profile != "test-agent-loop":
            raise ValueError(
                f"unsupported test-agent-loop approval resume profile: {normalized_profile}"
            )
        return ResolvedWorkflow(
            workflow=build_test_agent_loop_workflow(),
            profile="test-agent-loop",
            registry=build_test_agent_loop_registry(),
        )
    raise ValueError(f"unsupported approval resume workflow_id: {workflow_id}")


__all__ = [
    "ApprovalResumeApplicationService",
    "ApprovalWorkflowResumeResult",
    "DEFAULT_CHECKPOINT_STORE_PATH",
    "DailyRunApplicationService",
    "LiveSmokeApplicationService",
    "LiveSmokeResult",
    "LiveSmokeStatus",
    "RunApplicationService",
    "RunPersistenceApplicationService",
    "RunResolutionApplicationService",
    "WeeklyRunApplicationService",
    "build_agentic_daily_intelligence_workflow",
    "build_daily_intelligence_workflow",
    "build_test_agent_loop_registry",
    "build_test_agent_loop_workflow",
    "build_test_no_llm_registry",
    "build_test_no_llm_workflow",
    "persist_run_result",
    "repository_from_env",
]
