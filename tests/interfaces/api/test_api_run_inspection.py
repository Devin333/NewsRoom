from __future__ import annotations

import json

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.run_inspection_service import RunInspectionService


def test_run_inspection_api_lists_filters_and_reads_run_details(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-ok",
        status="succeeded",
        workflow_id="daily",
        profile="live-offline",
    )
    _write_run(
        tmp_path,
        "run-failed",
        status="failed",
        workflow_id="daily",
        profile="agentic-offline",
    )
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs?status=failed&limit=10")
    detail_response = client.get("/api/v1/runs/run-failed")
    manifest_response = client.get("/api/v1/runs/run-failed/manifest")

    assert response.status_code == 200
    assert response.json()["data"]["run_count"] == 1
    assert response.json()["data"]["runs"][0]["run_id"] == "run-failed"
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["status"] == "failed"
    assert detail_response.json()["data"]["artifact_dir"].endswith("run-failed")
    assert manifest_response.status_code == 200
    assert manifest_response.json()["data"]["manifest"]["workflow_id"] == "daily"


def test_run_inspection_api_missing_run_uses_run_not_found(tmp_path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "run_not_found"


def test_run_inspection_api_filters_events_and_lists_steps(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        events=[
            {"event_type": "step_started", "step_id": "collect", "payload": {}},
            {"event_type": "step_succeeded", "step_id": "collect", "payload": {}},
            {"event_type": "step_started", "step_id": "write", "payload": {}},
        ],
    )
    client = TestClient(_app(tmp_path))

    events_response = client.get(
        "/api/v1/runs/run-1/events?event_type=step_started&step_id=collect"
    )
    steps_response = client.get("/api/v1/runs/run-1/steps")

    assert events_response.status_code == 200
    assert events_response.json()["data"]["event_count"] == 1
    assert events_response.json()["data"]["events"][0]["step_id"] == "collect"
    assert steps_response.status_code == 200
    assert [step["step_id"] for step in steps_response.json()["data"]["steps"]] == [
        "collect",
        "write",
    ]


def test_run_inspection_api_lists_artifacts(tmp_path) -> None:
    _write_run(tmp_path, "run-1")
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/artifacts")
    artifact_response = client.get("/api/v1/runs/run-1/artifacts/report_markdown")

    assert response.status_code == 200
    assert response.json()["data"]["artifact_count"] >= 2
    assert artifact_response.status_code == 200
    assert artifact_response.json()["data"]["content"] == "# Report\n"


def _app(root):
    return create_app(
        run_inspection_service_factory=lambda: RunInspectionService(root),
        artifact_service_factory=lambda: ArtifactInspectionService(root),
        audit_emitter_factory=None,
    )


def _write_run(
    root,
    run_id,
    *,
    status="succeeded",
    workflow_id="daily",
    profile="live-offline",
    events=None,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    actual_events = events or [
        {"event_type": "workflow_started", "run_id": run_id, "payload": {}},
        {"event_type": f"workflow_{status}", "run_id": run_id, "payload": {}},
    ]
    manifest = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_version": "1.0",
        "profile": profile,
        "status": status,
        "started_at": "2026-05-14T01:00:00Z",
        "finished_at": "2026-05-14T01:00:01Z",
        "path": ["collect", "write"],
        "steps": {
            "collect": {"status": "succeeded", "outputs": {"items": []}},
            "write": {"status": status, "outputs": {"report": "ok"}},
        },
        "artifacts": {
            "events": "events.jsonl",
            "report_markdown": "report.md",
            "step_results": "step_results.json",
        },
        "step_count": 2,
        "event_count": len(actual_events),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in actual_events) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (run_dir / "step_results.json").write_text(
        json.dumps(manifest["steps"]),
        encoding="utf-8",
    )
