# pyright: reportUnsupportedDunderAll=false
from __future__ import annotations

from pathlib import Path
from typing import Any

from framework import RunResult
from interfaces.services.approval_resume_service import (
    DEFAULT_CHECKPOINT_STORE_PATH,
    ApprovalResumeApplicationService,
    ApprovalWorkflowResumeResult,
    build_default_approval_resume_service,
)
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.daily_run_service import DailyRunApplicationService, build_default_daily_run_service
from interfaces.services.live_smoke_service import (
    LiveSmokeApplicationService,
    LiveSmokeResult,
    LiveSmokeStatus,
    build_default_live_smoke_service,
)
from interfaces.services.run_persistence_service import RunPersistenceApplicationService
from interfaces.services.weekly_run_service import WeeklyRunApplicationService, build_default_weekly_run_service
from infrastructure.storage.repository import persist_run_result, repository_from_env


class RunApplicationService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        memory_ingestion_service: Any | None = None,
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
        return build_default_live_smoke_service(
            run_daily_agentic=self.run_daily_agentic,
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
        return build_default_weekly_run_service(
            artifact_root=self.artifact_root,
            persistence_service=self._persistence_service(),
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
        return build_default_approval_resume_service(
            artifact_root=self.artifact_root,
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
        return build_default_daily_run_service(
            artifact_root=self.artifact_root,
            persistence_service=self._persistence_service(),
            memory_ingestion_service=self.memory_ingestion_service,
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


def __getattr__(name: str) -> Any:
    if name in {
        "ResolvedWorkflow",
        "RunResolutionApplicationService",
        "_ResolvedWorkflow",
        "_normalize_profile",
        "_normalize_workflow_id",
        "_resolve_approval_resume_workflow",
        "build_agentic_daily_intelligence_workflow",
        "build_daily_intelligence_workflow",
        "build_test_agent_loop_registry",
        "build_test_agent_loop_workflow",
        "build_test_no_llm_registry",
        "build_test_no_llm_workflow",
        "normalize_profile",
        "normalize_workflow_id",
        "resolve_approval_resume_workflow",
    }:
        from interfaces.services import run_resolution_service

        return getattr(run_resolution_service, name)
    if name == "_daily_runner_cls":
        from interfaces.services.daily_run_service import resolve_daily_runner_cls

        return resolve_daily_runner_cls
    if name in {"_live_smoke_readiness_issues", "_readiness_message"}:
        from interfaces.services import live_smoke_service

        return getattr(live_smoke_service, name.removeprefix("_"))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [  # noqa: F822 - several compatibility exports are resolved lazily by __getattr__.
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
    "_ResolvedWorkflow",
    "_daily_runner_cls",
    "_live_smoke_readiness_issues",
    "_normalize_profile",
    "_normalize_workflow_id",
    "_readiness_message",
    "_resolve_approval_resume_workflow",
    "build_agentic_daily_intelligence_workflow",
    "build_daily_intelligence_workflow",
    "build_test_agent_loop_registry",
    "build_test_agent_loop_workflow",
    "build_test_no_llm_registry",
    "build_test_no_llm_workflow",
    "persist_run_result",
    "repository_from_env",
]
