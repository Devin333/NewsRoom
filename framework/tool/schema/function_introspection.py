from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from framework.tool.models.definition import ToolDefinition
from framework.tool.schema.json_schema import build_json_schema
from framework.tool.schema.parameter import ToolParameter


class FunctionToolIntrospector:
    def definition_from_function(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
    ) -> ToolDefinition:
        tool_name = name or fn.__name__.replace("_", ".")
        if "." not in tool_name:
            tool_name = f"function.{tool_name}"
        return ToolDefinition(
            name=tool_name,
            description=self.description_from_docstring(fn),
            input_schema=build_json_schema(self.parameters_from_signature(fn)),
            side_effect="read_only",
            concurrency_safe=True,
        )

    def parameters_from_signature(self, fn: Callable[..., Any]) -> list[ToolParameter]:
        signature = inspect.signature(fn)
        return [
            ToolParameter.from_signature_parameter(parameter)
            for parameter in signature.parameters.values()
            if parameter.kind
            in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        ]

    def description_from_docstring(self, fn: Callable[..., Any]) -> str:
        return inspect.getdoc(fn) or ""
