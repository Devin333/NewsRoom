from __future__ import annotations

from core.framework.tools.models import (
    ToolCall,
    ToolObservation,
    ToolPermissionError,
    ToolPolicy,
    ToolResult,
    ToolRuntimeError,
    ToolStatus,
    timed_tool_call,
)
from core.framework.tools.redaction import redact_sensitive_values
from core.framework.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, call: ToolCall, policy: ToolPolicy) -> ToolObservation:
        def invoke() -> ToolResult:
            registered = self._registry.get(call.tool_name)

            if not policy.allows(call.tool_name):
                raise ToolPermissionError(
                    f"agent {call.requested_by_agent_id} is not allowed to call {call.tool_name}"
                )

            missing = [
                argument
                for argument in registered.definition.required_arguments
                if argument not in call.arguments
            ]
            if missing:
                raise ToolRuntimeError(
                    f"missing required arguments for {call.tool_name}: {', '.join(missing)}"
                )

            raw_output = registered.executor(call.arguments)
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                output=redact_sensitive_values(raw_output),
            )

        try:
            result, elapsed_ms = timed_tool_call(invoke)
        except ToolPermissionError as exc:
            result = ToolResult(
                status=ToolStatus.BLOCKED,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            elapsed_ms = 0.0
        except Exception as exc:
            result = ToolResult(
                status=ToolStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            elapsed_ms = 0.0

        return ToolObservation(call=call, result=result, elapsed_ms=elapsed_ms)
