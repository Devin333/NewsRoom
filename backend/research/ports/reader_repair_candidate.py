from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.research.domain.reader_repair import (
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairPatchCandidate,
)


READER_REPAIR_PATCH_CANDIDATE_TASK = "reader_repair_patch_candidate"
READER_REPAIR_APPLICATION_OBSERVATION_TASK = (
    "reader_repair_application_observation"
)


def _string_schema(*, maximum: int, minimum: int = 0) -> dict[str, Any]:
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def _array_schema(
    item_schema: dict[str, Any],
    *,
    maximum: int,
) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": maximum,
        "items": item_schema,
    }


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _key_value_projection_schema(
    *,
    value_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    projected_value_schema = value_schema or {
        "oneOf": [
            _string_schema(maximum=4_000),
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
        ]
    }
    return _object_schema(
        {
            "entries": _array_schema(
                _object_schema(
                    {
                        "key": _string_schema(maximum=256, minimum=1),
                        "value": projected_value_schema,
                    }
                ),
                maximum=128,
            )
        }
    )


def _proposal_schema(
    model_type: type[Any],
    *,
    root_owned_fields: frozenset[str],
) -> dict[str, Any]:
    schema = deepcopy(model_type.model_json_schema())
    _remove_schema_keyword(schema, "discriminator")
    _remove_schema_property(schema, "metadata")
    for field_name in root_owned_fields:
        _remove_direct_schema_property(schema, field_name)

    definitions = schema.get("$defs")
    if isinstance(definitions, dict):
        for definition in definitions.values():
            if not isinstance(definition, dict):
                continue
            properties = definition.get("properties")
            if not isinstance(properties, dict) or "op" not in properties:
                evidence_refs = (
                    properties.get("evidence_refs")
                    if isinstance(properties, dict)
                    else None
                )
                if isinstance(evidence_refs, dict):
                    evidence_refs["minItems"] = 1
                    evidence_refs["maxItems"] = 32
            else:
                _remove_direct_schema_property(definition, "operation_id")
                _remove_direct_schema_property(
                    definition,
                    "expected_before_checksum",
                )
                required = list(definition.get("required", []))
                if "op" not in required:
                    required.append("op")
                definition["required"] = required
                source_refs = properties.get("source_refs")
                if isinstance(source_refs, dict):
                    source_refs["minItems"] = 1
                    source_refs["maxItems"] = 32

        analysis = definitions.get("ResearchAnalysis")
        if isinstance(analysis, dict):
            properties = analysis.get("properties")
            if isinstance(properties, dict) and "quality" in properties:
                properties["quality"] = _key_value_projection_schema()
        table = definitions.get("ResearchTable")
        if isinstance(table, dict):
            properties = table.get("properties")
            rows = properties.get("rows") if isinstance(properties, dict) else None
            if isinstance(rows, dict):
                rows["items"] = _key_value_projection_schema()
        evidence_pack = definitions.get("ResearchEvidencePack")
        if isinstance(evidence_pack, dict):
            properties = evidence_pack.get("properties")
            if isinstance(properties, dict) and "coverage" in properties:
                properties["coverage"] = _key_value_projection_schema(
                    value_schema={
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    }
                )

    _strict_and_bound_schema(schema)
    patch_operations = schema.get("properties", {}).get("patch_operations")
    if isinstance(patch_operations, dict):
        patch_operations["minItems"] = 1
        patch_operations["maxItems"] = 8
    observations = schema.get("properties", {}).get("observations")
    if isinstance(observations, dict):
        observations["minItems"] = 1
        observations["maxItems"] = 16
    return schema


def _remove_schema_keyword(value: Any, keyword: str) -> None:
    if isinstance(value, dict):
        value.pop(keyword, None)
        for item in value.values():
            _remove_schema_keyword(item, keyword)
    elif isinstance(value, list):
        for item in value:
            _remove_schema_keyword(item, keyword)


def _remove_schema_property(value: Any, field_name: str) -> None:
    if isinstance(value, dict):
        _remove_direct_schema_property(value, field_name)
        for item in value.values():
            _remove_schema_property(item, field_name)
    elif isinstance(value, list):
        for item in value:
            _remove_schema_property(item, field_name)


def _remove_direct_schema_property(
    value: dict[str, Any],
    field_name: str,
) -> None:
    properties = value.get("properties")
    if isinstance(properties, dict):
        properties.pop(field_name, None)
    required = value.get("required")
    if isinstance(required, list):
        value["required"] = [item for item in required if item != field_name]


def _strict_and_bound_schema(value: Any) -> None:
    if isinstance(value, dict):
        schema_type = value.get("type")
        if schema_type == "object":
            value["additionalProperties"] = False
        elif schema_type == "array":
            value.setdefault("maxItems", 64)
        elif schema_type == "string":
            value.setdefault("maxLength", 8_192)
        for item in value.values():
            _strict_and_bound_schema(item)
    elif isinstance(value, list):
        for item in value:
            _strict_and_bound_schema(item)


_READER_REPAIR_CANDIDATE_TASK_SCHEMAS = {
    READER_REPAIR_PATCH_CANDIDATE_TASK: _proposal_schema(
        ReaderRepairPatchCandidate,
        root_owned_fields=frozenset(
            {"candidate_id", "target_region_refs", "metadata"}
        ),
    ),
    READER_REPAIR_APPLICATION_OBSERVATION_TASK: _proposal_schema(
        ReaderRepairApplicationObservationCandidate,
        root_owned_fields=frozenset(
            {
                "candidate_id",
                "application_id",
                "source_refs",
                "input_bindings",
                "metadata",
            }
        ),
    ),
}


def reader_repair_candidate_task_schemas() -> dict[str, dict[str, Any]]:
    """Return isolated provider schemas for the two candidate-only tasks."""

    return deepcopy(_READER_REPAIR_CANDIDATE_TASK_SCHEMAS)


__all__ = [
    "READER_REPAIR_APPLICATION_OBSERVATION_TASK",
    "READER_REPAIR_PATCH_CANDIDATE_TASK",
    "reader_repair_candidate_task_schemas",
]
