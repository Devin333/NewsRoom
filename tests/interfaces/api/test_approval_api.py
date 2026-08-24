from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.api.openapi import export_openapi_schema


def test_legacy_approval_routes_are_not_registered() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))

    for method, path in (
        ("get", "/api/v1/approvals"),
        ("post", "/api/v1/approvals"),
        ("get", "/api/v1/approvals/approval-1"),
        ("post", "/api/v1/approvals/approval-1/approve"),
        ("post", "/api/v1/approvals/approval-1/reject"),
        ("post", "/api/v1/approvals/approval-1/resume-context"),
    ):
        response = (
            client.post(path, json={})
            if method == "post"
            else client.get(path)
        )
        assert response.status_code == 404


def test_openapi_exposes_graph_wait_identity_and_no_legacy_approval_paths() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))
    schema = export_openapi_schema(client.app)
    paths = schema["paths"]
    schemas = schema["components"]["schemas"]

    assert "/api/v2/graph-runs/{run_id}/waits/{node_instance_id}/approval" in paths
    assert "/api/v1/approvals" not in paths
    assert "ApprovalView" not in schemas
    wait_schema = schemas["HarnessWaitInspectionView"]["properties"]
    for field in ("graph_id", "graph_version", "graph_ref", "graph_checksum"):
        assert field in wait_schema
