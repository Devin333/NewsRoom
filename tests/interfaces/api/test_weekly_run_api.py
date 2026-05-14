from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.run_service import RunApplicationService


def test_weekly_run_api_aggregates_real_daily_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)
    run_service = RunApplicationService(artifact_root=tmp_path)
    daily = run_service.run_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
        run_id="api-weekly-daily",
    )
    client = TestClient(
        create_app(run_service_factory=lambda: RunApplicationService(artifact_root=tmp_path))
    )

    response = client.post(
        "/api/v1/runs/weekly",
        json={
            "topic": "AI policy",
            "source_limit": 5,
            "period_start": "2026-05-01T00:00:00Z",
            "period_end": "2026-05-20T00:00:00Z",
            "run_id": "api-weekly-run",
        },
    )
    payload = response.json()

    assert daily.status.value == "succeeded"
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["run_id"] == "api-weekly-run"
    assert payload["data"]["workflow_id"] == "weekly-intelligence"
    assert payload["data"]["status"] == "succeeded"
    assert payload["data"]["task_status"] is None
    assert payload["data"]["run_status"] == "succeeded"
    assert payload["data"]["report_status"] == "final"
    assert payload["data"]["report_id"] == "api-weekly-run:final"
    assert payload["data"]["manifest_ref"]["artifact_id"] == "manifest"
    assert payload["data"]["manifest_ref"]["run_id"] == "api-weekly-run"
    artifact_ids = {artifact["artifact_id"] for artifact in payload["data"]["artifact_refs"]}
    assert {"manifest", "report_json", "report_markdown"}.issubset(artifact_ids)
    assert payload["data"]["output"]["weekly_metrics"]["source_report_count"] == 1


def test_weekly_run_api_returns_unified_error_for_invalid_period(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)
    client = TestClient(
        create_app(run_service_factory=lambda: RunApplicationService(artifact_root=tmp_path))
    )

    response = client.post(
        "/api/v1/runs/weekly",
        json={
            "period_start": "2026-05-20T00:00:00Z",
            "period_end": "2026-05-01T00:00:00Z",
        },
    )
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_weekly_run_request"
    assert "period_start must be before period_end" in payload["error"]["message"]
