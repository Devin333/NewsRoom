from __future__ import annotations

from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.routing import APIRoute

from interfaces.models import (
    ApiError,
    ApiMeta,
    ApiResponse,
    ApprovalView,
    MemorySearchResponse,
    PageRequest,
    GraphRunDetail,
    RunEventView,
    RunEventsApiResponse,
    RunEventsData,
    GraphRunListItem,
    GraphRunCancellationRequest,
    RunResponse,
    ScheduleView,
    SourceHealthView,
)


OPENAPI_TAGS = [
    {"name": "health", "description": "Health and diagnostics endpoints."},
    {"name": "runs", "description": "Graph run creation and inspection."},
    {"name": "reports", "description": "Report catalog, detail, search, and actions."},
    {"name": "projects", "description": "Projects product module, rankings, tools, cases, lab, collections, and watchlist."},
    {"name": "research", "description": "Research paper analysis, reader payload, Q&A, and Harness trace endpoints."},
    {"name": "memory", "description": "Memory search and indexing."},
    {"name": "sources", "description": "Source catalog, health, and probes."},
    {"name": "workers", "description": "Worker and queue status."},
    {"name": "approvals", "description": "Human approval lifecycle."},
    {"name": "storage", "description": "Storage metrics and retention planning."},
    {"name": "mcp", "description": "MCP catalog and capability endpoints."},
    {"name": "admin", "description": "Administrative diagnostics."},
]

CONTRACT_MODELS = (
    ApiError,
    ApiMeta,
    ApiResponse,
    ApprovalView,
    MemorySearchResponse,
    PageRequest,
    GraphRunDetail,
    RunEventView,
    RunEventsApiResponse,
    RunEventsData,
    GraphRunListItem,
    GraphRunCancellationRequest,
    RunResponse,
    ScheduleView,
    SourceHealthView,
)


def configure_openapi_contract(api: FastAPI) -> None:
    api.openapi_tags = list(OPENAPI_TAGS)
    for route in api.routes:
        if not isinstance(route, APIRoute):
            continue
        route.tags = cast(list[str | Enum], [_tag_for_path(route.path)])
        route.operation_id = _operation_id(route)
        if _is_json_api_route(route) and route.response_model is None:
            route.response_model = ApiResponse
    api.openapi_schema = None


def export_openapi_schema(app: FastAPI | None = None) -> dict[str, Any]:
    if app is None:
        from interfaces.api.app import create_app

        app = create_app(audit_emitter_factory=None)
    schema = deepcopy(app.openapi())
    _ensure_contract_schemas(schema)
    _ensure_api_response_references(schema)
    return schema


def write_openapi_schema(
    path: str | Path = "docs/api/openapi.json",
    *,
    app: FastAPI | None = None,
) -> dict[str, Any]:
    import json

    schema = export_openapi_schema(app)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return schema


def summarize_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    info = schema.get("info") or {}
    paths = schema.get("paths") or {}
    components = schema.get("components") or {}
    schemas = components.get("schemas") if isinstance(components, dict) else {}
    return {
        "title": str(info.get("title") or ""),
        "version": str(info.get("version") or ""),
        "openapi": str(schema.get("openapi") or ""),
        "path_count": len(paths) if isinstance(paths, dict) else 0,
        "schema_count": len(schemas) if isinstance(schemas, dict) else 0,
    }


def _operation_id(route: APIRoute) -> str:
    method = _primary_method(route).lower()
    domain = _operation_domain(route.path)
    action = _operation_action(method, _route_path_parts(route.path))
    return f"{domain}_{action}"


def _primary_method(route: APIRoute) -> str:
    methods = sorted(method for method in (route.methods or {"GET"}) if method not in {"HEAD", "OPTIONS"})
    return methods[0] if methods else "GET"


def _path_part_name(part: str) -> str:
    if part.startswith("{") and part.endswith("}"):
        name = part[1:-1].strip().replace("-", "_")
        return name if name.endswith("_id") else f"{name}_id"
    return part.replace("-", "_")


def _route_path_parts(path: str) -> list[str]:
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) >= 2 and parts[0] == "api" and parts[1].startswith("v"):
        return parts[2:]
    return parts


def _operation_domain(path: str) -> str:
    if path.startswith("/health"):
        return "health"
    parts = _route_path_parts(path)
    if not parts:
        return "root"
    first = _path_part_name(parts[0])
    if first == "queues":
        return "queues"
    if first == "search":
        return "reports"
    if first == "artifacts":
        return "storage"
    return first


def _operation_action(method: str, path_parts: list[str]) -> str:
    tail = path_parts[1:] if path_parts else []
    static_parts = [_path_part_name(part) for part in tail if not _is_path_param(part)]
    if method == "get":
        if not tail:
            return "root" if path_parts and path_parts[0] == "health" else "list"
        if len(tail) == 1 and _is_path_param(tail[0]):
            return "get"
        if static_parts:
            if _is_path_param(tail[-1]):
                return "get_" + "_".join([*static_parts, _path_part_name(tail[-1])])
            if len(static_parts) == 1 and static_parts[0] in {"catalog", "capabilities", "latest"}:
                return static_parts[0]
            return "get_" + "_".join(static_parts)
        return "get"
    if method == "post":
        if not tail:
            return "create"
        if static_parts:
            if static_parts[0] == "operations":
                return "_".join(static_parts[1:] or static_parts)
            return "_".join(static_parts)
        return "create"
    if method == "delete":
        if not static_parts:
            return "delete"
        return "delete_" + "_".join(static_parts)
    if method == "patch":
        if not static_parts:
            return "update"
        return "update_" + "_".join(static_parts)
    return method


def _is_path_param(part: str) -> bool:
    return part.startswith("{") and part.endswith("}")


def _tag_for_path(path: str) -> str:
    if path.startswith("/health"):
        return "health"
    if path.startswith("/api/v1/admin"):
        return "admin"
    if path.startswith("/api/v2/graph-runs"):
        return "runs"
    if path.startswith("/api/v1/artifacts"):
        return "storage"
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) >= 3 and parts[0] == "api" and parts[1].startswith("v"):
        tag = parts[2]
        if tag == "queues":
            return "workers"
        if tag == "search":
            return "reports"
        return tag if tag in _tag_names() else "admin"
    return "admin"


def _tag_names() -> set[str]:
    return {tag["name"] for tag in OPENAPI_TAGS}


def _is_json_api_route(route: APIRoute) -> bool:
    if route.path in {
        "/api/v2/graph-runs/{run_id}/events/stream",
    }:
        return False
    return True


def _ensure_contract_schemas(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for model in CONTRACT_MODELS:
        if model.__name__ in schemas:
            continue
        if hasattr(model, "model_json_schema"):
            schemas[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
        else:
            schemas[model.__name__] = model.schema(ref_template="#/components/schemas/{model}")


def _ensure_api_response_references(schema: dict[str, Any]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return
    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            if path.endswith("/events/stream"):
                response_content = (
                    operation.setdefault("responses", {})
                    .setdefault("200", {"description": "Successful Response"})
                    .setdefault("content", {})
                )
                response_content.pop("application/json", None)
                response_content.setdefault("text/event-stream", {})
                continue
            content = (
                operation.setdefault("responses", {})
                .setdefault("200", {"description": "Successful Response"})
                .setdefault("content", {})
            )
            if "text/event-stream" in content:
                continue
            response_schema = "RunEventsApiResponse" if path.endswith("/events") else "ApiResponse"
            content["application/json"] = {
                "schema": {"$ref": f"#/components/schemas/{response_schema}"}
            }
