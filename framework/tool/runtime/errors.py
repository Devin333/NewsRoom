from __future__ import annotations


class ToolRuntimeError(RuntimeError):
    """Base exception for ToolRuntime failures."""


class ToolDefinitionError(ToolRuntimeError):
    """Raised when a tool definition is invalid."""


class ToolPermissionError(ToolRuntimeError):
    """Raised when an agent is not allowed to call a tool."""


class ToolTimeoutError(ToolRuntimeError):
    """Raised when a tool exceeds its execution timeout."""


class ToolSecretError(ToolRuntimeError):
    """Raised when a tool secret cannot be safely resolved."""
