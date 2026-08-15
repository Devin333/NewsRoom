from __future__ import annotations

import json
from hashlib import sha256

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.run_inspection_service import RunInspectionService
from tests.fixtures.graph_runs import (
    rewrite_graph_terminal_manifest,
    write_graph_terminal_run,
)
from tests.fixtures.workflow_runs import rewrite_manifest, write_canonical_terminal_run


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
    write_graph_terminal_run(
        tmp_path,
        files={
            "output": ("output.json", {"status": "ok"}),
            "report_markdown": ("report.md", "# Report\n"),
        },
    )
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/artifacts")
    artifact_response = client.get("/api/v1/runs/run-1/artifacts/report_markdown")

    assert response.status_code == 200
    assert response.json()["data"]["artifact_count"] >= 2
    assert artifact_response.status_code == 200
    assert artifact_response.json()["data"]["content"] == "# Report\n"


def test_run_inspection_api_distinguishes_invalid_artifact_path_from_missing(tmp_path) -> None:
    write_graph_terminal_run(
        tmp_path,
        "run-1",
        files={"report_markdown": ("report.md", "# Report\n")},
    )
    client = TestClient(_app(tmp_path))

    invalid = client.get("/api/v1/runs/run:stream/artifacts/report_markdown")
    missing = client.get("/api/v1/runs/run-1/artifacts/missing")

    invalid_payload = invalid.json()
    missing_payload = missing.json()
    assert invalid.status_code == 400
    assert invalid_payload["success"] is False
    assert invalid_payload["data"] is None
    assert invalid_payload["error"]["code"] == "invalid_artifact_path"
    assert "# Report" not in json.dumps(invalid_payload)
    assert missing.status_code == 404
    assert missing_payload["success"] is False
    assert missing_payload["data"] is None
    assert missing_payload["error"]["code"] == "artifact_not_found"
    assert "# Report" not in json.dumps(missing_payload)


def test_run_inspection_api_rejects_unsafe_run_id_with_400(tmp_path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run:stream/artifacts")

    payload = response.json()
    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "invalid_artifact_path"


def test_run_inspection_api_real_replay_rejects_tampered_artifact_without_data(
    tmp_path,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").write_text(
        json.dumps({"result": "tampered-api-secret"}),
        encoding="utf-8",
    )
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/replay")
    payload = response.json()

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "artifact_checksum_mismatch"
    assert "tampered-api-secret" not in json.dumps(payload)


def test_run_inspection_api_real_artifact_detail_rejects_missing_checksum_without_content(
    tmp_path,
) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    manifest = fixture.manifest.to_dict()
    manifest["artifacts"][0].pop("content_checksum")
    rewrite_graph_terminal_manifest(fixture, manifest)
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/artifacts/output")
    payload = response.json()

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "artifact_metadata_corrupt"
    assert "fixture-secret-token" not in json.dumps(payload)


def test_run_inspection_api_real_replay_rejects_invalid_canonical_manifest_without_data(
    tmp_path,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = dict(fixture.manifest)
    manifest["schema_version"] = "newsroom.workflow_run_manifest.v999"
    rewrite_manifest(fixture, manifest)
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/replay")
    payload = response.json()

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "artifact_metadata_corrupt"
    assert "fixture-secret-token" not in json.dumps(payload)


def test_run_inspection_api_real_artifact_detail_wraps_unsafe_manifest_path_as_metadata(
    tmp_path,
) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    manifest = fixture.manifest.to_dict()
    manifest["artifacts"][0]["relative_path"] = "../outside.json"
    rewrite_graph_terminal_manifest(fixture, manifest)
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/artifacts/output")
    payload = response.json()

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "artifact_metadata_corrupt"
    assert "fixture-secret-token" not in json.dumps(payload)


def test_run_inspection_api_real_artifact_detail_maps_missing_file_without_content(
    tmp_path,
) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    fixture.artifact_path("output").unlink()
    client = TestClient(_app(tmp_path))

    response = client.get("/api/v1/runs/run-1/artifacts/output")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "artifact_not_found"
    assert "fixture-secret-token" not in json.dumps(payload)


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
    artifact_contents = {
        "events": (
            "events.jsonl",
            ("\n".join(json.dumps(event) for event in actual_events) + "\n").encode("utf-8"),
        ),
        "report_markdown": ("report.md", b"# Report\n"),
        "step_results": (
            "step_results.json",
            json.dumps(
                {
                    "collect": {"status": "succeeded", "outputs": {"items": []}},
                    "write": {"status": status, "outputs": {"report": "ok"}},
                }
            ).encode("utf-8"),
        ),
    }
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
            artifact_key: relative_path
            for artifact_key, (relative_path, _) in artifact_contents.items()
        },
        "artifact_metadata": {
            artifact_key: {
                "checksum": sha256(content).hexdigest(),
                "content_type": (
                    "application/x-ndjson"
                    if relative_path.endswith(".jsonl")
                    else "application/json"
                    if relative_path.endswith(".json")
                    else "text/markdown"
                ),
                "size_bytes": len(content),
            }
            for artifact_key, (relative_path, content) in artifact_contents.items()
        },
        "step_count": 2,
        "event_count": len(actual_events),
        "output": output or {},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path, content in artifact_contents.values():
        (run_dir / relative_path).write_bytes(content)
