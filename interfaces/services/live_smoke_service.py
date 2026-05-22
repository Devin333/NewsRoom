from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from business.boards.cross_board.profiles import PROFILE_AGENTIC_LIVE
from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.diagnose_service import DiagnoseCheck, DiagnoseResult


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


class LiveSmokeApplicationService:
    def __init__(
        self,
        *,
        diagnostic_service_factory: Callable,
        run_daily_agentic: Callable,
        live_profile: str,
    ) -> None:
        self.diagnostic_service_factory = diagnostic_service_factory
        self.run_daily_agentic = run_daily_agentic
        self.live_profile = live_profile

    def run_live_smoke(
        self,
        *,
        topic: str = "AI",
        source_limit: int = 3,
        run_id: str | None = None,
        skip_if_unready: bool = True,
    ) -> LiveSmokeResult:
        diagnostics = self.diagnostic_service_factory().run()
        readiness_issues = live_smoke_readiness_issues(diagnostics)
        if readiness_issues:
            message = readiness_message(readiness_issues)
            return LiveSmokeResult(
                status="skipped" if skip_if_unready else "failed",
                message=message,
                diagnostics=diagnostics,
                topic=topic,
                source_limit=source_limit,
            )

        result = self.run_daily_agentic(
            profile=self.live_profile,
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


def live_smoke_readiness_issues(diagnostics: DiagnoseResult) -> list[DiagnoseCheck]:
    return [
        check
        for check in diagnostics.checks
        if check.check_id in _LIVE_SMOKE_READINESS_CHECKS and check.status in {"warning", "error"}
    ]


def readiness_message(readiness_issues: list[DiagnoseCheck]) -> str:
    issue_ids = ", ".join(check.check_id for check in readiness_issues)
    return f"live smoke readiness checks are not ready: {issue_ids}"


def build_default_live_smoke_service(*, run_daily_agentic: Callable) -> LiveSmokeApplicationService:
    from interfaces.services.diagnose_service import DiagnosticApplicationService

    return LiveSmokeApplicationService(
        diagnostic_service_factory=DiagnosticApplicationService,
        run_daily_agentic=run_daily_agentic,
        live_profile=PROFILE_AGENTIC_LIVE,
    )


__all__ = [
    "LiveSmokeApplicationService",
    "LiveSmokeResult",
    "LiveSmokeStatus",
    "build_default_live_smoke_service",
    "live_smoke_readiness_issues",
    "readiness_message",
]
