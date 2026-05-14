from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition, ToolDefinitionError, ToolRuntimeError


def validate_tool_arguments(definition: ToolDefinition, arguments: dict[str, Any]) -> None:
    normalized_arguments = normalize_tool_arguments(definition, arguments)
    arguments.clear()
    arguments.update(normalized_arguments)


def normalize_tool_arguments(
    definition: ToolDefinition,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    schema = definition.input_schema or {}
    if not isinstance(schema, dict):
        raise ToolDefinitionError(f"input_schema must be an object for tool {definition.name}")
    if not isinstance(arguments, dict):
        raise ToolRuntimeError(f"arguments for {definition.name} must be an object")

    properties = schema.get("properties", {})
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise ToolDefinitionError(f"properties must be an object for tool {definition.name}")

    normalized = dict(arguments)
    for argument_name, property_schema in properties.items():
        if argument_name in normalized:
            continue
        if not isinstance(property_schema, dict):
            raise ToolDefinitionError(
                f"property schema must be an object for {definition.name}.{argument_name}"
            )
        if "default" in property_schema:
            normalized[argument_name] = property_schema["default"]

    required = definition.required_arguments
    missing = [argument for argument in required if argument not in normalized]
    if missing:
        raise ToolRuntimeError(
            f"missing required arguments for {definition.name}: {', '.join(missing)}"
        )

    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(normalized) - set(properties))
        if unexpected:
            raise ToolRuntimeError(
                f"unexpected arguments for {definition.name}: {', '.join(unexpected)}"
            )

    for argument_name, value in normalized.items():
        property_schema = properties.get(argument_name)
        if property_schema is None:
            continue
        if not isinstance(property_schema, dict):
            raise ToolDefinitionError(
                f"property schema must be an object for {definition.name}.{argument_name}"
            )
        _validate_argument_schema(definition.name, argument_name, value, property_schema)
    return normalized


def _validate_argument_schema(
    tool_name: str,
    argument_name: str,
    value: Any,
    schema: dict[str, Any],
) -> None:
    if "enum" in schema:
        allowed_values = schema["enum"]
        if not isinstance(allowed_values, list):
            raise ToolDefinitionError(f"enum must be a list for {tool_name}.{argument_name}")
        if value not in allowed_values:
            raise ToolRuntimeError(
                f"argument {argument_name} for {tool_name} must be one of: "
                f"{', '.join(str(item) for item in allowed_values)}"
            )

    expected_type = schema.get("type")
    if expected_type is None:
        return
    expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
    if not all(isinstance(item, str) for item in expected_types):
        raise ToolDefinitionError(f"type must be a string or string list for {tool_name}.{argument_name}")
    if not any(_matches_json_type(value, item) for item in expected_types):
        raise ToolRuntimeError(
            f"argument {argument_name} for {tool_name} must be "
            f"{' or '.join(expected_types)}, got {type(value).__name__}"
        )


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    raise ToolDefinitionError(f"unsupported JSON schema type: {expected_type}")
