from __future__ import annotations

from typing import Any


class LLMStructuredOutputValidationError(ValueError):
    """Raised when parsed structured output violates the requested schema."""


def validate_structured_output(value: Any, schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise LLMStructuredOutputValidationError("schema must be an object")
    _validate_value(value, schema, "$")


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(schema, dict):
        raise LLMStructuredOutputValidationError(f"{path}: schema must be an object")

    if "enum" in schema:
        allowed = schema["enum"]
        if not isinstance(allowed, list):
            raise LLMStructuredOutputValidationError(f"{path}: enum must be an array")
        if value not in allowed:
            raise LLMStructuredOutputValidationError(f"{path}: value is not in enum")

    expected_type = schema.get("type")
    if expected_type is None:
        if "properties" in schema or "required" in schema:
            expected_type = "object"
        elif "items" in schema:
            expected_type = "array"

    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not all(isinstance(item, str) for item in expected_types):
            raise LLMStructuredOutputValidationError(f"{path}: type must be a string or array")
        if not any(_matches_json_type(value, item) for item in expected_types):
            raise LLMStructuredOutputValidationError(
                f"{path}: expected {' or '.join(expected_types)}, got {type(value).__name__}"
            )

    if isinstance(value, dict):
        _validate_object(value, schema, path)
    elif isinstance(value, list):
        _validate_array(value, schema, path)


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    required = schema.get("required", [])
    if required is None:
        required = []
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise LLMStructuredOutputValidationError(f"{path}: required must be an array of strings")
    for property_name in required:
        if property_name not in value:
            raise LLMStructuredOutputValidationError(
                f"{path}: missing required property: {property_name}"
            )

    properties = schema.get("properties", {})
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise LLMStructuredOutputValidationError(f"{path}: properties must be an object")

    for property_name, property_schema in properties.items():
        if property_name in value:
            _validate_value(value[property_name], property_schema, f"{path}.{property_name}")

    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(value) - set(properties))
        if unexpected:
            raise LLMStructuredOutputValidationError(
                f"{path}: unexpected properties: {', '.join(unexpected)}"
            )


def _validate_array(value: list[Any], schema: dict[str, Any], path: str) -> None:
    item_schema = schema.get("items")
    if item_schema is None:
        return
    if not isinstance(item_schema, dict):
        raise LLMStructuredOutputValidationError(f"{path}: items must be an object")
    for index, item in enumerate(value):
        _validate_value(item, item_schema, f"{path}[{index}]")


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise LLMStructuredOutputValidationError(f"unsupported schema type: {expected_type}")
