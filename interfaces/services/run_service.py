from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.framework import RunResult
from core.framework.specs import WorkflowStatus
from interfaces.services.diagnose_service import DiagnoseCheck, DiagnoseResult, DiagnosticApplicationService
from interfaces.services.report_service import ReportApplicationService
from storage.memory import MemoryIngestionService, memory_ingestion_service_from_env
from storage.repository import persist_run_result, repository_from_env
from workflows.daily_intelligence import DailyIntelligenceRunner
from workflows.daily_intelligence.test_agent_loop import run_test_agent_loop
from workflows.daily_intelligence.test_no_llm import run_test_no_llm
from workflows.weekly_intelligence import PROFILE_WEEKLY, WeeklyIntelligenceRunner


LiveSmokeStatus = Literal["succeeded", "failed", "skipped"]
_LIVE_SMOKE_READINESS_CHECKS = {"source_config", "model_config", "dashscope_api_key"}


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
        repository = repository_from_env(artifact_root=self.artifact_root)
        repository.migrate()
        result = DailyIntelligenceRunner(artifact_root=self.artifact_root).run(
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

        result = self.run_daily(
            profile="live",
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


def _live_smoke_readiness_issues(diagnostics: DiagnoseResult) -> list[DiagnoseCheck]:
    return [
        check
        for check in diagnostics.checks
        if check.check_id in _LIVE_SMOKE_READINESS_CHECKS and check.status in {"warning", "error"}
    ]


def _readiness_message(readiness_issues: list[DiagnoseCheck]) -> str:
    issue_ids = ", ".join(check.check_id for check in readiness_issues)
    return f"live smoke readiness checks are not ready: {issue_ids}"
