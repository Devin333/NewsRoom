from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.framework import RunResult, WorkflowRunner
from core.framework.specs import WorkflowSpec
from core.framework.specs import WorkflowStatus
from core.framework.workflow import FunctionStepRegistry
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.diagnose_service import DiagnoseCheck, DiagnoseResult, DiagnosticApplicationService
from interfaces.services.report_service import ReportApplicationService
from storage.checkpoint import LocalJsonCheckpointStore
from storage.memory import MemoryIngestionService, memory_ingestion_service_from_env
from storage.repository import persist_run_result, repository_from_env
from workflows.daily_intelligence import AgenticDailyIntelligenceRunner, DailyIntelligenceRunner
from workflows.daily_intelligence import build_agentic_daily_intelligence_workflow, build_daily_intelligence_workflow
from workflows.daily_intelligence import build_test_agent_loop_registry
from workflows.daily_intelligence import build_test_agent_loop_workflow
from workflows.daily_intelligence import build_test_no_llm_registry
from workflows.daily_intelligence import build_test_no_llm_workflow
from workflows.daily_intelligence.artifact_publisher import build_daily_intelligence_artifact_publishers
from workflows.daily_intelligence.profiles import (
    AGENTIC_DAILY_WORKFLOW_ID,
    LEGACY_DAILY_WORKFLOW_ID,
    PROFILE_AGENTIC_LIVE,
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    daily_agentic_enabled,
)
from workflows.daily_intelligence.test_agent_loop import run_test_agent_loop
from workflows.daily_intelligence.test_no_llm import run_test_no_llm
from workflows.daily_intelligence.runner import PROFILE_LIVE, PROFILE_LIVE_OFFLINE
from workflows.weekly_intelligence import PROFILE_WEEKLY, WeeklyIntelligenceRunner


LiveSmokeStatus = Literal["succeeded", "failed", "skipped"]
_LIVE_SMOKE_READINESS_CHECKS = {"source_config", "model_config", "dashscope_api_key"}
DEFAULT_CHECKPOINT_STORE_PATH = ".newsroom/checkpoints"


@dataclass(frozen=True)
class ApprovalWorkflowResumeResult:
    approval_context: dict[str, object]
    run_result: RunResult

    def to_dict(self) -> dict[str, object]:
        return {
            "approval_context": self.approval_context,
            "run_result": self.run_result.to_dict(),
            "run_id": self.run_result.run_id,
            "workflow_id": self.run_result.workflow_id,
            "workflow_version": self.run_result.workflow_version,
            "status": self.run_result.status.value,
            "output": self.run_result.to_dict()["output"],
            "artifact_dir": self.run_result.artifact_dir,
            "manifest_path": self.run_result.manifest_path,
            "events_path": self.run_result.events_path,
            "error": self.run_result.error,
        }


@dataclass(frozen=True)
class _ResolvedWorkflow:
    workflow: WorkflowSpec
    profile: str
    registry: FunctionStepRegistry


@dataclass(frozen=True)
class LiveSmokeResult:
    status: LiveSmokeStatus
    message: str
    diagnostics: DiagnoseResult
    topic: str
    source_limit: int
    run_result: RunResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "message": self.message,
            "profile": "live",
            "topic": self.topic,
            "source_limit": self.source_limit,
            "run_id": self.run_result.run_id if self.run_result else None,
            "artifact_dir": self.run_result.artifact_dir if self.run_result else None,
            "diagnostics": self.diagnostics.to_dict(),
            "run_result": self.run_result.to_dict() if self.run_result else None,
        }


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
        return run_test_no_llm(
            artifact_root=self.artifact_root,
            request={"topic": topic},
            run_id=run_id,
        )

    def run_test_agent_loop(self, *, topic: str, run_id: str | None = None) -> RunResult:
        return run_test_agent_loop(
            artifact_root=self.artifact_root,
            request={"topic": topic},
            run_id=run_id,
        )

    def run_daily(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None = None,
    ) -> RunResult:
        return self._run_daily_with_runner(
            runner_cls=_daily_runner_cls(profile),
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
        return self._run_daily_with_runner(
            runner_cls=AgenticDailyIntelligenceRunner,
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
        diagnostics = DiagnosticApplicationService().run()
        readiness_issues = _live_smoke_readiness_issues(diagnostics)
        if readiness_issues:
            message = _readiness_message(readiness_issues)
            return LiveSmokeResult(
                status="skipped" if skip_if_unready else "failed",
                message=message,
                diagnostics=diagnostics,
                topic=topic,
                source_limit=source_limit,
            )

        result = self.run_daily_agentic(
            profile=PROFILE_AGENTIC_LIVE,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )
        if result.status == WorkflowStatus.SUCCEEDED:
            status: LiveSmokeStatus = "succeeded"
            message = "live smoke succeeded"
        else:
            status = "failed"
            message = result.error.get("message") if result.error else "live smoke failed"
        return LiveSmokeResult(
            status=status,
            message=str(message),
            diagnostics=diagnostics,
            topic=topic,
            source_limit=source_limit,
            run_result=result,
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
        repository = repository_from_env(artifact_root=self.artifact_root)
        repository.migrate()
        report_repository = ReportApplicationService(artifact_root=self.artifact_root).repository
        result = WeeklyIntelligenceRunner(
            artifact_root=self.artifact_root,
            report_repository=report_repository,
        ).run(
            language=language,
            topic=topic,
            source_limit=source_limit,
            period_start=period_start,
            period_end=period_end,
            run_id=run_id,
        )
        persist_run_result(
            repository,
            result,
            profile=PROFILE_WEEKLY,
            migrate=False,
        )
        return result

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
        resolved = _resolve_approval_resume_workflow(workflow_id, profile=profile)
        context = (
            approval_service or ApprovalApplicationService()
        ).build_resume_context(approval_id, decision_key=decision_key)
        runner = WorkflowRunner(
            artifact_root=self.artifact_root,
            function_registry=resolved.registry,
            checkpoint_store=LocalJsonCheckpointStore(checkpoint_store_path),
            artifact_publishers=build_daily_intelligence_artifact_publishers()
            if resolved.workflow.workflow_id.startswith("daily-intelligence")
            else None,
        )
        run_result = runner.resume_from_approval_context(
            resolved.workflow,
            context,
            profile=resolved.profile,
            run_id=run_id,
        )
        return ApprovalWorkflowResumeResult(
            approval_context=context.to_dict(),
            run_result=run_result,
        )

    def _index_memory_if_configured(self, result: RunResult, *, topic: str) -> None:
        memory_service = self.memory_ingestion_service or memory_ingestion_service_from_env()
        if memory_service is None:
            return
        ingestion_result = memory_service.ingest_run_output(
            result.output,
            run_id=result.run_id,
            report_id=f"{result.run_id}:final",
            topic=topic,
        )
        result.output["memory_ingestion_result"] = ingestion_result.to_dict()

    def _run_daily_with_runner(
        self,
        *,
        runner_cls,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None,
    ) -> RunResult:
        repository = repository_from_env(artifact_root=self.artifact_root)
        repository.migrate()
        result = runner_cls(artifact_root=self.artifact_root).run(
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )
        persist_run_result(
            repository,
            result,
            profile=profile,
            migrate=False,
        )
        self._index_memory_if_configured(result, topic=topic)
        return result


def _live_smoke_readiness_issues(diagnostics: DiagnoseResult) -> list[DiagnoseCheck]:
    return [
        check
        for check in diagnostics.checks
        if check.check_id in _LIVE_SMOKE_READINESS_CHECKS and check.status in {"warning", "error"}
    ]


def _readiness_message(readiness_issues: list[DiagnoseCheck]) -> str:
    issue_ids = ", ".join(check.check_id for check in readiness_issues)
    return f"live smoke readiness checks are not ready: {issue_ids}"


def _resolve_approval_resume_workflow(
    workflow_id: str,
    *,
    profile: str | None,
) -> _ResolvedWorkflow:
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
        return _ResolvedWorkflow(
            workflow=build_agentic_daily_intelligence_workflow(actual_profile),
            profile=actual_profile,
            registry=runner._function_registry(actual_profile),
        )
    if normalized_workflow in {"test-no-llm", "daily-intelligence-test-no-llm"}:
        if normalized_profile and normalized_profile != "test-no-llm":
            raise ValueError(
                f"unsupported test-no-llm approval resume profile: {normalized_profile}"
            )
        return _ResolvedWorkflow(
            workflow=build_test_no_llm_workflow(),
            profile="test-no-llm",
            registry=build_test_no_llm_registry(),
        )
    if normalized_workflow in {"test-agent-loop", "daily-intelligence-test-agent-loop"}:
        if normalized_profile and normalized_profile != "test-agent-loop":
            raise ValueError(
                f"unsupported test-agent-loop approval resume profile: {normalized_profile}"
            )
        return _ResolvedWorkflow(
            workflow=build_test_agent_loop_workflow(),
            profile="test-agent-loop",
            registry=build_test_agent_loop_registry(),
        )
    raise ValueError(f"unsupported approval resume workflow_id: {workflow_id}")


def _normalize_workflow_id(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("workflow_id is required")
    return normalized


def _normalize_profile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _daily_runner_cls(profile: str):
    if profile in {PROFILE_LIVE, PROFILE_LIVE_OFFLINE}:
        return AgenticDailyIntelligenceRunner
    return AgenticDailyIntelligenceRunner if daily_agentic_enabled(profile) else DailyIntelligenceRunner
