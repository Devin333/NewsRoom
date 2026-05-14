from __future__ import annotations

import re
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

    if "const" in schema and value != schema["const"]:
        raise LLMStructuredOutputValidationError(f"{path}: value does not match const")

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
    elif isinstance(value, str):
        _validate_string(value, schema, path)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(value, schema, path)


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    min_properties = _optional_non_negative_int(schema, "minProperties", path)
    if min_properties is not None and len(value) < min_properties:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at least {min_properties} properties, got {len(value)}"
        )
    max_properties = _optional_non_negative_int(schema, "maxProperties", path)
    if max_properties is not None and len(value) > max_properties:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at most {max_properties} properties, got {len(value)}"
        )

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
    min_items = _optional_non_negative_int(schema, "minItems", path)
    if min_items is not None and len(value) < min_items:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at least {min_items} items, got {len(value)}"
        )
    max_items = _optional_non_negative_int(schema, "maxItems", path)
    if max_items is not None and len(value) > max_items:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at most {max_items} items, got {len(value)}"
        )
    if schema.get("uniqueItems") is True:
        seen = set()
        for index, item in enumerate(value):
            key = _stable_value_key(item)
            if key in seen:
                raise LLMStructuredOutputValidationError(
                    f"{path}: duplicate item at index {index}"
                )
            seen.add(key)

    item_schema = schema.get("items")
    if item_schema is None:
        return
    if not isinstance(item_schema, dict):
        raise LLMStructuredOutputValidationError(f"{path}: items must be an object")
    for index, item in enumerate(value):
        _validate_value(item, item_schema, f"{path}[{index}]")


def _validate_string(value: str, schema: dict[str, Any], path: str) -> None:
    min_length = _optional_non_negative_int(schema, "minLength", path)
    if min_length is not None and len(value) < min_length:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected string length at least {min_length}, got {len(value)}"
        )
    max_length = _optional_non_negative_int(schema, "maxLength", path)
    if max_length is not None and len(value) > max_length:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected string length at most {max_length}, got {len(value)}"
        )
    pattern = schema.get("pattern")
    if pattern is None:
        return
    if not isinstance(pattern, str):
        raise LLMStructuredOutputValidationError(f"{path}: pattern must be a string")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise LLMStructuredOutputValidationError(f"{path}: invalid pattern: {exc}") from exc
    if not compiled.search(value):
        raise LLMStructuredOutputValidationError(f"{path}: string does not match pattern")


def _validate_number(value: int | float, schema: dict[str, Any], path: str) -> None:
    minimum = _optional_number(schema, "minimum", path)
    if minimum is not None and value < minimum:
        raise LLMStructuredOutputValidationError(f"{path}: expected number >= {minimum}, got {value}")
    maximum = _optional_number(schema, "maximum", path)
    if maximum is not None and value > maximum:
        raise LLMStructuredOutputValidationError(f"{path}: expected number <= {maximum}, got {value}")


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


def _optional_non_negative_int(schema: dict[str, Any], keyword: str, path: str) -> int | None:
    if keyword not in schema:
        return None
    value = schema[keyword]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LLMStructuredOutputValidationError(
            f"{path}: {keyword} must be a non-negative integer"
        )
    return value


def _optional_number(schema: dict[str, Any], keyword: str, path: str) -> float | None:
    if keyword not in schema:
        return None
    value = schema[keyword]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise LLMStructuredOutputValidationError(f"{path}: {keyword} must be a number")
    return float(value)


def _stable_value_key(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(
            f"{key}:{_stable_value_key(value[key])}" for key in sorted(value)
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_stable_value_key(item) for item in value) + "]"
    return repr(value)
