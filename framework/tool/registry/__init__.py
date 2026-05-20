from __future__ import annotations

from typing import Any

from framework.tool.registry.registry import (
    DuplicateToolPolicy,
    RegisteredTool,
    ToolRegistry,
    ToolRegistryValidationResult,
)

_LAZY_EXPORTS = {
    "ToolCatalog": "framework.tool.registry.catalog",
    "ToolCatalogEntry": "framework.tool.registry.catalog",
    "ToolCatalogNamespace": "framework.tool.registry.catalog",
    "ToolDiscovery": "framework.tool.registry.discovery",
    "ToolNamespace": "framework.tool.registry.namespace",
    "ToolResolver": "framework.tool.registry.resolver",
    "build_builtin_dangerous_registry": "framework.tool.registry.catalog",
    "build_builtin_dangerous_tool_registry": "framework.tool.registry.catalog",
    "build_builtin_safe_registry": "framework.tool.registry.catalog",
    "build_builtin_safe_tool_registry": "framework.tool.registry.catalog",
    "build_builtin_tool_registry": "framework.tool.registry.catalog",
    "build_tool_catalog": "framework.tool.registry.catalog",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "DuplicateToolPolicy",
    "RegisteredTool",
    "ToolCatalog",
    "ToolCatalogEntry",
    "ToolCatalogNamespace",
    "ToolDiscovery",
    "ToolNamespace",
    "ToolRegistry",
    "ToolRegistryValidationResult",
    "ToolResolver",
    "build_builtin_dangerous_registry",
    "build_builtin_dangerous_tool_registry",
    "build_builtin_safe_registry",
    "build_builtin_safe_tool_registry",
    "build_builtin_tool_registry",
    "build_tool_catalog",
]
