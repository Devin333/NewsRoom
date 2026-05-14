from __future__ import annotations

from copy import deepcopy
from typing import Any

from interfaces.api.app import create_app
from interfaces.models import ApiError, ApiResponse, RunResponse


_CONTRACT_MODELS = (ApiError, ApiResponse, RunResponse)


def export_openapi_schema() -> dict[str, Any]:
    schema = deepcopy(create_app().openapi())
    _ensure_contract_schemas(schema)
    return schema


def _ensure_contract_schemas(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for model in _CONTRACT_MODELS:
        if model.__name__ in schemas:
            continue
        if hasattr(model, "model_json_schema"):
            schemas[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
        else:
            schemas[model.__name__] = model.schema(ref_template="#/components/schemas/{model}")


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
