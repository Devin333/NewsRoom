from __future__ import annotations

import ast
from pathlib import Path

from interfaces.api import create_app
from interfaces.api.openapi import export_openapi_schema


RESEARCH_ROUTER = Path("interfaces/api/routers/research.py")
RESEARCH_SERVICE = Path("interfaces/services/research_service.py")


def test_research_routes_are_registered_under_new_research_namespace() -> None:
    app = create_app(audit_emitter_factory=None)
    paths = {route.path for route in app.routes}

    assert {
        "/api/v1/research/papers/analyze",
        "/api/v1/research/papers/{paper_id}/analysis",
        "/api/v1/research/papers/{paper_id}/reader",
        "/api/v1/research/papers/{paper_id}/ask",
        "/api/v1/research/runs/{run_id}/trace",
    } <= paths


def test_research_openapi_contract_uses_response_envelope_and_tags() -> None:
    schema = export_openapi_schema()
    analyze = schema["paths"]["/api/v1/research/papers/analyze"]["post"]

    assert "research" in {tag["name"] for tag in schema["tags"]}
    assert analyze["tags"] == ["research"]
    assert analyze["operationId"] == "research_papers_analyze"
    assert analyze["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiResponse"
    }


def test_research_interface_does_not_import_old_paper_modules() -> None:
    forbidden_roots = {
        "business.boards.paper_radar",
        "interfaces.api.routers.papers",
        "interfaces.services.paper_service",
    }

    for path in (RESEARCH_ROUTER, RESEARCH_SERVICE):
        module = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(module)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom)
        )
        assert not any(import_name.startswith(root) for import_name in imports for root in forbidden_roots), path


def test_research_router_uses_research_service_factory_only() -> None:
    source = RESEARCH_ROUTER.read_text(encoding="utf-8")

    assert "research_service_factory" in source
    assert "papers_service_factory" not in source
    assert "/api/v1/papers" not in source
