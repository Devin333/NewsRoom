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


def test_run_inspection_api_includes_quality_trace_preview(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-quality",
        status="blocked",
        workflow_id="daily",
        profile="live-offline",
        output={
            "quality_result": {
                "decision": "blocked",
                "route": "human_review",
                "metadata": {
                    "citation_failure_categories": [{"code": "unsupported_claims", "count": 1, "items": ["Summary: Unsupported claim"]}]
                },
            },
            "citation_check_result": {
                "unsupported_claims": ["Summary: Unsupported claim"],
                "rejected_claim_usage": [],
            },
            "support_matrix": {
                "unsupported_sections": ["Summary"],
            },
            "evidence_bundle": {"bundle_id": "bundle-1"},
            "candidate_claims": [
                {"claim_id": "claim-1", "source_evidence_ids": ["ev-1"]}
            ],
            "verified_findings": {
                "accepted_claims": [{"claim_id": "claim-1", "supporting_evidence_ids": ["ev-1"], "supporting_sources": ["https://example.com/a"]}],
                "rejected_claims": [],
                "uncertain_claims": [],
            },
        },
    )
    client = TestClient(_app(tmp_path))

    detail_response = client.get("/api/v1/runs/run-quality")
    payload = detail_response.json()

    assert detail_response.status_code == 200
    assert payload["data"]["output_preview"]["quality_trace"]["decision"] == "blocked"
    assert payload["data"]["output_preview"]["quality_trace"]["route"] == "human_review"
    assert payload["data"]["output_preview"]["quality_trace"]["unsupported_sections"] == ["Summary"]
    assert payload["data"]["output_preview"]["quality_trace"]["quality_lineage"]["claim_count"] == 1
    assert payload["data"]["output_preview"]["quality_trace"]["quality_lineage"]["supporting_evidence_ids"] == ["ev-1"]


    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "run_not_found"


def test_run_inspection_api_includes_llm_trace_preview(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-llm",
        status="succeeded",
        workflow_id="daily",
        profile="live-offline",
        output={
            "llm_route_manifest": {
                "selected_deployment_id": "primary",
                "fallback_used": True,
                "fallback_count": 1,
                "metrics": {
                    "provider_error_count": 1,
                    "cooldown_skip_count": 0,
                },
                "budget_check": {"within_budget": True, "violations": []},
                "global_budget_check": {"within_budget": True, "violations": []},
            },
            "llm_router_events": [
                {"event_type": "llm_route_started"},
                {"event_type": "llm_fallback_selected"},
            ],
        },
    )
    client = TestClient(_app(tmp_path))

    detail_response = client.get("/api/v1/runs/run-llm")
    payload = detail_response.json()

    assert detail_response.status_code == 200
    assert payload["data"]["output_preview"]["llm_trace"]["selected_deployment_id"] == "primary"
    assert payload["data"]["output_preview"]["llm_trace"]["fallback_used"] is True
    assert payload["data"]["output_preview"]["llm_trace"]["router_event_count"] == 2


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


def test_run_inspection_api_distinguishes_invalid_artifact_path_from_missing(tmp_path) -> None:
    _write_run(tmp_path, "run-unsafe")
    manifest_path = tmp_path / "run-unsafe" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["report_markdown"] = "../outside.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(_app(tmp_path))

    invalid = client.get("/api/v1/runs/run-unsafe/artifacts/report_markdown")
    missing = client.get("/api/v1/runs/run-unsafe/artifacts/missing")

    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_artifact_path"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "artifact_not_found"


def test_run_inspection_api_rejects_unsafe_run_id_with_400(tmp_path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run:stream/artifacts")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_artifact_path"


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
    output=None,
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
        "output": output or {},
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
