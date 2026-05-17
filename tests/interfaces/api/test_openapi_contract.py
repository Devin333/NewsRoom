from __future__ import annotations

from interfaces.api import create_app
from interfaces.api.openapi import export_openapi_schema


def test_openapi_schema_generates_core_contract() -> None:
    schema = export_openapi_schema()

    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "NewsRoom API"
    assert "/api/v1/runs" in schema["paths"]
    assert "ApiResponse" in schema["components"]["schemas"]
    assert "schema_version" in schema["components"]["schemas"]["ApiResponse"]["properties"]


def test_openapi_operation_ids_are_unique_and_stable() -> None:
    schema = export_openapi_schema()
    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]

    assert operation_ids
    assert len(operation_ids) == len(set(operation_ids))
    assert "runs_create" in operation_ids
    assert "runs_get_events" in operation_ids
    assert "reports_latest" in operation_ids
    assert "memory_search" in operation_ids
    assert "mcp_catalog" in operation_ids


def test_all_api_v1_openapi_operations_have_tags() -> None:
    schema = export_openapi_schema()

    missing_tags = []
    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            if not operation.get("tags"):
                missing_tags.append((method, path))

    assert missing_tags == []


def test_json_api_operations_reference_api_response_envelope() -> None:
    schema = export_openapi_schema()

    for path, path_item in schema["paths"].items():
        if path in {"/api/v1/runs/{run_id}/progress", "/api/v1/runs/{run_id}/events/stream"}:
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            content = operation["responses"]["200"].get("content", {})
            json_schema = content.get("application/json", {}).get("schema", {})
            assert json_schema == {"$ref": "#/components/schemas/ApiResponse"}, path


def test_create_app_routes_have_operation_id_and_tags_before_schema_export() -> None:
    app = create_app(audit_emitter_factory=None)
    api_routes = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/")
    ]

    assert api_routes
    assert all(getattr(route, "operation_id", None) for route in api_routes)
    assert all(getattr(route, "tags", None) for route in api_routes)
