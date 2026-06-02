from __future__ import annotations

import json
from pathlib import Path

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


def test_diagnostic_service_reports_source_config_parse_error_without_exposing_file_content(
    tmp_path: Path,
) -> None:
    secret = "sk-test-secret-value"
    path = tmp_path / "sources.yaml"
    path.write_text(f"api_key: [{secret}\n", encoding="utf-8")
    service = DiagnosticApplicationService(env={"NEWS_SOURCES_CONFIG": str(path)}, checks=[])

    check = service._check_source_config()

    assert check.check_id == "source_config"
    assert check.status == "error"
    assert "not valid YAML" in check.message
    assert str(path) in check.message
    assert secret not in str(check.to_dict())


def test_diagnostic_service_warns_for_missing_model_env_without_exposing_secret() -> None:
    service = DiagnosticApplicationService(env={}, checks=[])

    check = service._check_model_config()

    assert check.status == "warning"
    assert "DASHSCOPE_API_KEY" in check.message
    assert "sk-" not in str(check.to_dict())


def test_diagnostic_service_reports_model_config_schema_error(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "routez": {},
                "model_groups": {
                    "writer-group": {
                        "deployments": [
                            {
                                "deployment_id": "writer-primary",
                                "provider": "openai-compatible",
                                "provider_name": "test-provider",
                                "model": "test-model",
                                "api_base": "https://llm.example/v1",
                                "api_key": "${TEST_LLM_API_KEY}",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    service = DiagnosticApplicationService(env={"NEWS_MODELS_CONFIG": str(path)}, checks=[])

    check = service._check_model_config()

    assert check.check_id == "model_config"
    assert check.status == "error"
    assert "unsupported field(s): routez" in check.message
    assert check.details["path"] == str(path)


def test_diagnostic_service_reports_model_config_parse_error_without_exposing_file_content(
    tmp_path: Path,
) -> None:
    secret = "sk-test-secret-value"
    path = tmp_path / "models.yaml"
    path.write_text(f"api_key: [{secret}\n", encoding="utf-8")
    service = DiagnosticApplicationService(env={"NEWS_MODELS_CONFIG": str(path)}, checks=[])

    check = service._check_model_config()

    assert check.check_id == "model_config"
    assert check.status == "error"
    assert "not valid YAML" in check.message
    assert str(path) in check.message
    assert secret not in str(check.to_dict())


def test_diagnostic_service_model_config_does_not_expose_secret() -> None:
    service = DiagnosticApplicationService(env={"DASHSCOPE_API_KEY": "secret-value"}, checks=[])

    check = service._check_model_config()

    assert check.status == "ok"
    assert "secret-value" not in str(check.to_dict())
