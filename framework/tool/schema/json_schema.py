from __future__ import annotations

from collections.abc import Callable
from typing import Any

from framework.tool.schema.parameter import ToolParameter


class ToolJsonSchemaBuilder:
    def build(self, parameters: list[ToolParameter]) -> dict[str, Any]:
        return build_json_schema(parameters)

    def from_function(self, fn: Callable[..., Any]) -> dict[str, Any]:
        from framework.tool.schema.function_introspection import FunctionToolIntrospector

        return build_json_schema(FunctionToolIntrospector().parameters_from_signature(fn))


def build_json_schema(parameters: list[ToolParameter]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": [parameter.name for parameter in parameters if parameter.required],
        "properties": {
            parameter.name: parameter.to_json_schema()
            for parameter in parameters
        },
        "additionalProperties": False,
    }
