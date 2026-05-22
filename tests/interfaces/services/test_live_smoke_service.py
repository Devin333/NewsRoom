from __future__ import annotations

from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.diagnose_service import DiagnoseCheck, DiagnoseResult
from interfaces.services.live_smoke_service import LiveSmokeApplicationService


def test_live_smoke_service_preserves_skipped_semantics() -> None:
    service = LiveSmokeApplicationService(
        diagnostic_service_factory=lambda: _Diagnostics(
            [DiagnoseCheck("model_config", "Model", "warning", "missing")]
        ),
        run_daily_agentic=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
        live_profile="agentic-live",
    )

    result = service.run_live_smoke(skip_if_unready=True)

    assert result.status == "skipped"
    assert "model_config" in result.message


def test_live_smoke_service_runs_agentic_when_ready() -> None:
    calls = []
    service = LiveSmokeApplicationService(
        diagnostic_service_factory=lambda: _Diagnostics(
            [DiagnoseCheck("model_config", "Model", "ok", "ok")]
        ),
        run_daily_agentic=lambda **kwargs: calls.append(kwargs) or RunResult(
            run_id="live",
            workflow_id="daily",
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={},
        ),
        live_profile="agentic-live",
    )

    result = service.run_live_smoke(topic="AI", source_limit=2)

    assert result.status == "succeeded"
    assert calls == [{"profile": "agentic-live", "topic": "AI", "source_limit": 2, "run_id": None}]


class _Diagnostics:
    def __init__(self, checks):
        self.checks = checks

    def run(self):
        return DiagnoseResult.from_checks(self.checks)
