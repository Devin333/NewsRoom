from interfaces.services.diagnose_service import (
    DiagnoseCheck,
    DiagnoseResult,
    DiagnosticApplicationService,
)


def test_diagnose_result_aggregates_warning() -> None:
    result = DiagnoseResult.from_checks(
        [
            DiagnoseCheck("redis", "Redis", "ok", "ok"),
            DiagnoseCheck("dashscope", "DashScope", "warning", "missing"),
            DiagnoseCheck("postgres", "PostgreSQL", "skipped", "not configured"),
        ]
    )

    assert result.status == "warning"
    assert result.summary == "1 ok, 1 warning, 0 error, 1 skipped"


def test_diagnostic_service_runs_injected_checks() -> None:
    service = DiagnosticApplicationService(
        checks=[
            lambda: DiagnoseCheck("redis", "Redis", "ok", "ok"),
            lambda: DiagnoseCheck("qdrant", "Qdrant", "error", "down"),
        ]
    )

    result = service.run()

    assert result.status == "error"
    assert [check.check_id for check in result.checks] == ["redis", "qdrant"]


def test_dashscope_key_check_does_not_expose_secret() -> None:
    service = DiagnosticApplicationService(env={"DASHSCOPE_API_KEY": "secret-value"}, checks=[])

    check = service._check_dashscope_key()

    assert check.status == "ok"
    assert "secret-value" not in str(check.to_dict())


def test_diagnostic_service_validates_tracked_source_config() -> None:
    service = DiagnosticApplicationService(env={}, checks=[])

    check = service._check_source_config()

    assert check.status == "ok"
    assert check.details["source_count"] >= 3


def test_diagnostic_service_warns_for_missing_model_env_without_exposing_secret() -> None:
    service = DiagnosticApplicationService(env={}, checks=[])

    check = service._check_model_config()

    assert check.status == "warning"
    assert "DASHSCOPE_API_KEY" in check.message
    assert "sk-" not in str(check.to_dict())


def test_diagnostic_service_model_config_does_not_expose_secret() -> None:
    service = DiagnosticApplicationService(env={"DASHSCOPE_API_KEY": "secret-value"}, checks=[])

    check = service._check_model_config()

    assert check.status == "ok"
    assert "secret-value" not in str(check.to_dict())
