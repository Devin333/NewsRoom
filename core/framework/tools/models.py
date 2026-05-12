from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Any
from uuid import uuid4

from core.framework.tools.redaction import redact_sensitive_values


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


class ToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    side_effect: str = "none"
    is_dangerous: bool = False
    requires_approval: bool = False
    timeout_seconds: float | None = None
    max_attempts: int | None = None
    concurrency_safe: bool = False
    required_secret_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.name:
            raise ToolDefinitionError("tool name is required")
        if "." not in self.name or any(not segment for segment in self.name.split(".")):
            raise ToolDefinitionError(f"tool name must be namespaced: {self.name}")
        if not self.version:
            raise ToolDefinitionError(f"tool version is required for {self.name}")
        if any(not isinstance(name, str) or not name for name in self.required_secret_names):
            raise ToolDefinitionError(f"required secret names must be non-empty strings for {self.name}")

    @property
    def namespace(self) -> str:
        return self.name.split(".", maxsplit=1)[0]

    @property
    def tool_id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def required_arguments(self) -> list[str]:
        required = self.input_schema.get("required", [])
        if not isinstance(required, list):
            raise ToolDefinitionError(f"required arguments must be a list for tool {self.name}")
        return [str(item) for item in required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "side_effect": self.side_effect,
            "is_dangerous": self.is_dangerous,
            "requires_approval": self.requires_approval,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "concurrency_safe": self.concurrency_safe,
            "required_secret_names": list(self.required_secret_names),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ToolPolicy:
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    allow_mcp_tools: bool = False
    require_explicit_allowlist: bool = True
    allow_dangerous_tools: bool = False
    require_approval_for_side_effects: bool = True
    max_result_chars_inline: int = 8000
    spill_large_results_to_artifact: bool = True
    timeout_seconds_default: float | None = 30.0
    max_attempts_default: int = 1

    def allows(self, tool_name: str) -> bool:
        if tool_name in self.blocked_tools:
            return False
        if _is_mcp_tool(tool_name) and not self.allow_mcp_tools:
            return False
        if self.require_explicit_allowlist:
            return tool_name in self.allowed_tools
        return True

    def exposes(self, definition: ToolDefinition) -> bool:
        if not self.allows(definition.name):
            return False
        if definition.is_dangerous and not self.allow_dangerous_tools:
            return False
        return True


def _is_mcp_tool(tool_name: str) -> bool:
    return tool_name.startswith("mcp.")


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    requested_by_agent_id: str = ""
    call_id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": redact_sensitive_values(dict(self.arguments)),
            "requested_by_agent_id": self.requested_by_agent_id,
        }


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    relative_path: str
    content_type: str = "application/json"
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    output: Any = None
    output_summary: str | None = None
    artifact_refs: list[ArtifactRef] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    approval_id: str | None = None
    redacted: bool = True
    output_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "output": redact_sensitive_values(self.output),
            "output_summary": self.output_summary,
            "artifact_refs": [artifact_ref.to_dict() for artifact_ref in self.artifact_refs],
            "error_type": self.error_type,
            "error_message": self.error_message,
            "approval_id": self.approval_id,
            "redacted": self.redacted,
            "output_bytes": self.output_bytes,
        }


@dataclass(frozen=True)
class ToolObservation:
    call: ToolCall
    result: ToolResult
    elapsed_ms: float

    @property
    def status(self) -> ToolStatus:
        return self.result.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "call": self.call.to_dict(),
            "result": self.result.to_dict(),
            "elapsed_ms": self.elapsed_ms,
        }


ToolExecutorFn = Callable[[dict[str, Any]], Any]


def timed_tool_call(function: Callable[[], ToolResult]) -> tuple[ToolResult, float]:
    start = perf_counter()
    result = function()
    return result, (perf_counter() - start) * 1000
