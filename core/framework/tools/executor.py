from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.tools.models import (
    ArtifactRef,
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
from core.framework.tools.validation import validate_tool_arguments


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def execute(self, call: ToolCall, policy: ToolPolicy) -> ToolObservation:
        def invoke() -> ToolResult:
            registered = self._registry.get(call.tool_name)

            if not policy.allows(call.tool_name):
                raise ToolPermissionError(
                    f"agent {call.requested_by_agent_id} is not allowed to call {call.tool_name}"
                )

            safety_result = _safety_gate(registered.definition, policy)
            if safety_result is not None:
                return safety_result

            validate_tool_arguments(registered.definition, call.arguments)

            raw_output = registered.executor(call.arguments)
            safe_output = redact_sensitive_values(raw_output)
            return self._tool_result(call, safe_output, policy)

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

    def _tool_result(
        self,
        call: ToolCall,
        safe_output: Any,
        policy: ToolPolicy,
    ) -> ToolResult:
        output_bytes = _json_size_bytes(safe_output)
        if (
            policy.spill_large_results_to_artifact
            and output_bytes > policy.max_result_chars_inline
            and self._artifact_manager is not None
            and self._run_id is not None
        ):
            relative_path = f"tool_results/{call.call_id}.json"
            artifact_payload = {
                "call": call.to_dict(),
                "output": safe_output,
                "output_bytes": output_bytes,
            }
            path = self._artifact_manager.write_json(self._run_id, relative_path, artifact_payload)
            artifact_ref = ArtifactRef(
                artifact_id=f"tool_result:{call.call_id}",
                relative_path=relative_path,
                size_bytes=path.stat().st_size,
            )
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                output=None,
                output_summary=f"Tool result spilled to artifact: {relative_path}",
                artifact_refs=[artifact_ref],
                output_bytes=output_bytes,
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            output=safe_output,
            output_bytes=output_bytes,
        )


def _safety_gate(definition: Any, policy: ToolPolicy) -> ToolResult | None:
    if definition.is_dangerous and not policy.allow_dangerous_tools:
        return ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=f"dangerous tool is not allowed: {definition.name}",
        )
    if (
        policy.require_approval_for_side_effects
        and (definition.requires_approval or _has_side_effects(definition.side_effect))
    ):
        return ToolResult(
            status=ToolStatus.APPROVAL_REQUIRED,
            output_summary=f"Tool requires approval before execution: {definition.name}",
        )
    return None


def _has_side_effects(side_effect: str) -> bool:
    return side_effect not in {"", "none", "read_only"}


def _json_size_bytes(value: Any) -> int:
    return len(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
