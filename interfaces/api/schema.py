from __future__ import annotations

from copy import deepcopy
from typing import Any

from interfaces.api.app import create_app


def export_openapi_schema() -> dict[str, Any]:
    return deepcopy(create_app().openapi())


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
