from __future__ import annotations

from typing import TYPE_CHECKING, Any

from framework.tool.runtime.errors import (
    ToolDefinitionError,
    ToolPermissionError,
    ToolRuntimeError,
    ToolSecretError,
    ToolTimeoutError,
)

if TYPE_CHECKING:
    from framework.tool.runtime.batch_executor import ToolBatchExecutor
    from framework.tool.runtime.executor import ToolExecutor
    from framework.tool.runtime.mcp_adapter import MCPServerConfig, MCPToolAdapter
    from framework.tool.runtime.retry import ToolRetryController
    from framework.tool.runtime.sandbox import ToolSandbox
    from framework.tool.runtime.timeout import ToolTimeoutRunner, run_with_timeout

_LAZY_EXPORTS = {
    "MCPServerConfig": "framework.tool.runtime.mcp_adapter",
    "MCPToolAdapter": "framework.tool.runtime.mcp_adapter",
    "ToolBatchExecutor": "framework.tool.runtime.batch_executor",
    "ToolExecutor": "framework.tool.runtime.executor",
    "ToolRetryController": "framework.tool.runtime.retry",
    "ToolSandbox": "framework.tool.runtime.sandbox",
    "ToolTimeoutRunner": "framework.tool.runtime.timeout",
    "run_with_timeout": "framework.tool.runtime.timeout",
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
    "MCPServerConfig",
    "MCPToolAdapter",
    "ToolBatchExecutor",
    "ToolDefinitionError",
    "ToolExecutor",
    "ToolPermissionError",
    "ToolRetryController",
    "ToolRuntimeError",
    "ToolSandbox",
    "ToolSecretError",
    "ToolTimeoutError",
    "ToolTimeoutRunner",
    "run_with_timeout",
]
