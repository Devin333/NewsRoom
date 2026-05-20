from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.diagnose_service import DiagnoseCheck, DiagnoseResult
import interfaces.services.run_service as run_service_module
from interfaces.services.run_service import RunApplicationService


def test_run_live_smoke_skips_when_live_readiness_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        run_service_module,
        "DiagnosticApplicationService",
        lambda: _FakeDiagnosticService(
            [
                DiagnoseCheck("source_config", "Live source config", "ok", "ok"),
                DiagnoseCheck("model_config", "Live model config", "warning", "missing key"),
                DiagnoseCheck("redis", "Redis", "error", "down"),
            ]
        ),
    )

    class Service(RunApplicationService):
        def run_daily(self, **kwargs):
            raise AssertionError("live smoke must not run daily when readiness is missing")

    result = Service(artifact_root=tmp_path).run_live_smoke(topic="AI", source_limit=3)

    assert result.status == "skipped"
    assert "model_config" in result.message


def test_run_live_smoke_ignores_non_mvp_dependency_warnings(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        run_service_module,
        "DiagnosticApplicationService",
        lambda: _FakeDiagnosticService(
            [
                DiagnoseCheck("source_config", "Live source config", "ok", "ok"),
                DiagnoseCheck("model_config", "Live model config", "ok", "ok"),
                DiagnoseCheck("dashscope_api_key", "DashScope API key", "ok", "ok"),
                DiagnoseCheck("qdrant", "Qdrant", "error", "down"),
            ]
        ),
    )
    calls = []

    class Service(RunApplicationService):
        def run_daily_agentic(self, **kwargs):
            calls.append(kwargs)
            return RunResult(
                run_id="live-smoke",
                workflow_id="daily-intelligence-agentic",
                workflow_version="0.1.0",
                status=WorkflowStatus.SUCCEEDED,
                artifact_dir=str(tmp_path / "live-smoke"),
            )

    result = Service(artifact_root=tmp_path).run_live_smoke(topic="AI", source_limit=3)

    assert result.status == "succeeded"
    assert calls == [
        {
            "profile": "agentic-live",
            "topic": "AI",
            "source_limit": 3,
            "run_id": None,
        }
    ]
    assert result.to_dict()["run_id"] == "live-smoke"


class _FakeDiagnosticService:
    def __init__(self, checks: list[DiagnoseCheck]) -> None:
        self.checks = checks

    def run(self) -> DiagnoseResult:
        return DiagnoseResult.from_checks(self.checks)
