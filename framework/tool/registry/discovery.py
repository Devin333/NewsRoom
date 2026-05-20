from __future__ import annotations

from collections.abc import Callable
from typing import Any

from framework.tool.models.definition import ToolDefinition
from framework.tool.schema.function_introspection import FunctionToolIntrospector


class ToolDiscovery:
    def discover_from_module(self, module: Any) -> list[ToolDefinition]:
        functions = [
            value
            for value in vars(module).values()
            if callable(value) and getattr(value, "__module__", None) == getattr(module, "__name__", None)
        ]
        return self.discover_from_functions(functions)

    def discover_from_functions(self, functions: list[Callable[..., Any]]) -> list[ToolDefinition]:
        introspector = FunctionToolIntrospector()
        return [introspector.definition_from_function(function) for function in functions]
