from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.mcp_service import MCPApplicationService


def test_api_mcp_catalog_and_manifest_match_service() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))
    service = MCPApplicationService()

    catalog_response = client.get("/api/v1/mcp/catalog")
    manifest_response = client.get("/api/v1/mcp/manifest")
    capabilities_response = client.get("/api/v1/mcp/capabilities")

    assert catalog_response.status_code == 200
    assert manifest_response.status_code == 200
    assert capabilities_response.status_code == 200
    assert catalog_response.json()["data"] == service.catalog().to_dict()
    assert manifest_response.json()["data"] == service.capability_manifest().to_dict()
    assert capabilities_response.json()["data"] == manifest_response.json()["data"]


def test_api_mcp_tool_resource_and_prompt_results_are_enveloped() -> None:
    client = TestClient(
        create_app(
            mcp_service_factory=lambda: _FakeMCPService(),
            audit_emitter_factory=None,
        )
    )

    tool_response = client.post(
        "/api/v1/mcp/tools/news.report.latest/call",
        json={"arguments": {"limit": 1}},
    )
    resource_response = client.post(
        "/api/v1/mcp/resources/read",
        json={"uri": "news://reports/latest"},
    )
    prompt_response = client.post(
        "/api/v1/mcp/prompts/news.run.diagnose/get",
        json={"arguments": {"run_id": "run-1"}},
    )

    for response in [tool_response, resource_response, prompt_response]:
        payload = response.json()
        assert response.status_code == 200
        assert payload["success"] is True
        assert payload["request_id"]
        assert payload["schema_version"] == "1.0"

    assert tool_response.json()["data"]["tool_name"] == "news.report.latest"
    assert resource_response.json()["data"]["uri"] == "news://reports/latest"
    assert prompt_response.json()["data"]["name"] == "news.run.diagnose"


def test_api_mcp_artifact_path_failures_use_outer_http_error_envelope() -> None:
    client = TestClient(
        create_app(
            mcp_service_factory=lambda: _FailedMCPService("ArtifactPathError"),
            audit_emitter_factory=None,
        )
    )

    responses = [
        client.post(
            "/api/v1/mcp/tools/news.run.replay/call",
            json={"arguments": {"run_id": "run:stream"}},
        ),
        client.post(
            "/api/v1/mcp/resources/read",
            json={"uri": "news://runs/run:stream/artifacts/output"},
        ),
    ]

    for response in responses:
        payload = response.json()
        assert response.status_code == 400
        assert payload["success"] is False
        assert payload["ok"] is False
        assert payload["data"] is None
        assert payload["error"]["code"] == "invalid_artifact_path"
        assert payload["error"]["details"]["error_type"] == "ArtifactPathError"


@pytest.mark.parametrize(
    ("error_type", "expected_status", "expected_code"),
    [
        ("ArtifactChecksumMismatchError", 409, "artifact_checksum_mismatch"),
        ("ArtifactStoreMetadataError", 409, "artifact_metadata_corrupt"),
        ("ArtifactStoreRequiredError", 500, "artifact_store_unavailable"),
    ],
)
def test_api_mcp_reserves_typed_artifact_failure_http_mapping(
    error_type,
    expected_status,
    expected_code,
) -> None:
    client = TestClient(
        create_app(
            mcp_service_factory=lambda: _FailedMCPService(error_type),
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/mcp/tools/news.run.replay/call",
        json={"arguments": {"run_id": "run-1"}},
    )
    payload = response.json()

    assert response.status_code == expected_status
    assert payload["success"] is False
    assert payload["ok"] is False
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["details"]["error_type"] == error_type


def test_api_mcp_tool_call_requires_tool_specific_permission() -> None:
    client = TestClient(
        create_app(
            api_keys={"readonly-token": ["read-only"]},
            run_operation_service_factory=lambda: _FakeRunOperationService(),
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/mcp/tools/news.run.cancel/call",
        headers={"Authorization": "Bearer readonly-token"},
        json={
            "arguments": {
                "run_id": "run-1",
                "reason": "manual stop",
            }
        },
    )

    payload = response.json()
    assert response.status_code == 403
    assert payload["success"] is False
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["message"] == "missing required permission: write:runs"


def test_api_mcp_default_service_uses_injected_run_operation_service() -> None:
    fake_operations = _FakeRunOperationService()
    client = TestClient(
        create_app(
            run_operation_service_factory=lambda: fake_operations,
            audit_emitter_factory=None,
        )
    )

    response = client.post(
        "/api/v1/mcp/tools/news.run.cancel/call",
        json={
            "arguments": {
                "run_id": "run-1",
                "reason": "manual stop",
                "actor_id": "operator",
                "metadata": {"source": "api-mcp"},
            }
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["success"] is True
    assert payload["data"]["data"]["operation_type"] == "cancel_run"
    assert fake_operations.calls == [
        (
            "cancel_run",
            {
                "run_id": "run-1",
                "reason": "manual stop",
                "actor_id": "operator",
                "metadata": {"source": "api-mcp"},
            },
        )
    ]


class _FakeMCPService:
    def catalog(self):
        return _FakeResult({"tools": [], "resources": [], "prompts": []})

    def capability_manifest(self):
        return _FakeResult({"version": "1.0", "capabilities": [], "capability_count": 0})

    def call_tool(self, tool_name, arguments):
        return _FakeResult(
            {
                "tool_name": tool_name,
                "success": True,
                "data": {"arguments": arguments},
                "error_type": None,
                "error_message": None,
            }
        )

    def read_resource(self, uri):
        return _FakeResult(
            {
                "uri": uri,
                "success": True,
                "mime_type": "application/json",
                "data": {"ok": True},
                "error_type": None,
                "error_message": None,
            }
        )

    def get_prompt(self, prompt_name, arguments):
        return _FakeResult(
            {
                "name": prompt_name,
                "success": True,
                "description": "Prompt",
                "messages": [{"role": "user", "content": str(arguments)}],
                "error_type": None,
                "error_message": None,
            }
        )


class _FailedMCPService:
    def __init__(self, error_type) -> None:
        self.error_type = error_type

    def call_tool(self, tool_name, arguments):
        return _FakeResult(
            {
                "tool_name": tool_name,
                "success": False,
                "data": None,
                "error_type": self.error_type,
                "error_message": "artifact operation failed",
            }
        )

    def read_resource(self, uri):
        return _FakeResult(
            {
                "uri": uri,
                "success": False,
                "mime_type": "application/json",
                "data": None,
                "error_type": self.error_type,
                "error_message": "artifact operation failed",
            }
        )


class _FakeRunOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def cancel_run(self, run_id, *, reason=None, actor_id=None, metadata=None):
        self.calls.append(
            (
                "cancel_run",
                {
                    "run_id": run_id,
                    "reason": reason,
                    "actor_id": actor_id,
                    "metadata": dict(metadata or {}),
                },
            )
        )
        return _FakeResult(
            {
                "operation_id": "op-test",
                "operation_type": "cancel_run",
                "status": "accepted",
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)
