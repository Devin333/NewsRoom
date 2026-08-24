from __future__ import annotations

import json

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.run_inspection_service import GraphRunInspectionService
from business.research.graphs.contracts import RESEARCH_PAPER_ANALYSIS_GRAPH_ID
from tests.fixtures.graph_runs import (
    graph_index_reader,
    rewrite_graph_terminal_manifest,
    write_graph_terminal_run,
)


def _client(root) -> TestClient:
    return TestClient(
        create_app(
            graph_run_inspection_service_factory=lambda: GraphRunInspectionService(
                root,
                graph_index_reader=graph_index_reader(root),
            ),
            artifact_service_factory=lambda: ArtifactInspectionService(root),
            audit_emitter_factory=None,
        )
    )


def test_graph_run_inspection_lists_and_reads_graph_terminal_runs(tmp_path) -> None:
    write_graph_terminal_run(tmp_path, "run-ok", status="succeeded")
    write_graph_terminal_run(tmp_path, "run-failed", status="failed")
    client = _client(tmp_path)

    response = client.get("/api/v2/graph-runs?status=failed&limit=10")
    detail = client.get("/api/v2/graph-runs/run-failed")
    manifest = client.get("/api/v2/graph-runs/run-failed/manifest")

    assert response.status_code == 200
    assert response.json()["data"]["run_count"] == 1
    assert response.json()["data"]["runs"][0]["run_id"] == "run-failed"
    assert detail.status_code == 200
    assert detail.json()["data"]["graph_id"] == RESEARCH_PAPER_ANALYSIS_GRAPH_ID
    assert manifest.status_code == 200
    assert manifest.json()["data"]["manifest"]["graph_id"] == RESEARCH_PAPER_ANALYSIS_GRAPH_ID
    assert manifest.json()["data"]["manifest"]["graph_version"] == "1"


def test_graph_run_inspection_rejects_history_route_and_reports_missing_graph_run(tmp_path) -> None:
    client = _client(tmp_path)

    legacy = client.get("/api/v1/runs/run-missing")
    missing = client.get("/api/v2/graph-runs/run-missing")

    assert legacy.status_code == 404
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "graph_run_not_found"


def test_graph_run_artifacts_are_read_through_artifact_owner(tmp_path) -> None:
    write_graph_terminal_run(
        tmp_path,
        files={
            "output": ("output.json", {"status": "ok"}),
            "report_markdown": ("report.md", "# Report\n"),
        },
    )
    client = _client(tmp_path)

    listing = client.get("/api/v2/graph-runs/run-1/artifacts")
    detail = client.get("/api/v2/graph-runs/run-1/artifacts/report_markdown")

    assert listing.status_code == 200
    assert listing.json()["data"]["artifact_count"] == 2
    assert detail.status_code == 200
    assert detail.json()["data"]["content"] == "# Report\n"


def test_graph_artifact_integrity_failure_does_not_expose_tampered_content(tmp_path) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    fixture.artifact_path("output").write_text(
        json.dumps({"result": "tampered-secret"}),
        encoding="utf-8",
    )
    client = _client(tmp_path)

    replay = client.get("/api/v2/graph-runs/run-1/replay")
    artifact = client.get("/api/v2/graph-runs/run-1/artifacts/output")

    for response in (replay, artifact):
        assert response.status_code == 409
        payload = response.json()
        assert payload["data"] is None
        assert payload["error"]["code"] == "artifact_checksum_mismatch"
        assert "tampered-secret" not in json.dumps(payload)


def test_graph_manifest_metadata_integrity_failure_is_quarantined(tmp_path) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    manifest = fixture.manifest.to_dict()
    manifest["artifacts"][0].pop("content_checksum")
    rewrite_graph_terminal_manifest(fixture, manifest)
    client = _client(tmp_path)

    response = client.get("/api/v2/graph-runs/run-1/artifacts/output")

    assert response.status_code == 409
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "artifact_metadata_corrupt"
