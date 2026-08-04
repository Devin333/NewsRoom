from __future__ import annotations

from typing import Any

from framework.specs import StepSpec
from framework.tool import ToolCall, ToolPolicy
from framework.workflow.buffer import StepScopedDataBufferView
from framework.workflow.runners.base import StepExecutionError


def single_tool_call_from_step(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> ToolCall:
    raw_call = step.metadata.get("tool_call")
    if raw_call is None:
        tool_name = step.metadata.get("tool_name")
        if tool_name is None:
            raw_call = buffer.read(
                str(step.metadata.get("tool_call_key") or "tool_call")
            )
        else:
            arguments = step.metadata.get("arguments")
            if "arguments_key" in step.metadata:
                arguments = buffer.read(str(step.metadata["arguments_key"]))
            raw_call = {
                "tool_name": tool_name,
                "arguments": arguments or {},
                "call_id": step.metadata.get("call_id"),
                "requested_by_agent_id": step.metadata.get("requested_by_agent_id"),
            }
    return tool_call_from_payload(step, buffer, raw_call)


def tool_calls_from_step(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> list[ToolCall]:
    raw_calls = step.metadata.get("tool_calls")
    if raw_calls is None:
        raw_calls = buffer.read(
            str(step.metadata.get("tool_calls_key") or "tool_calls")
        )
    if not isinstance(raw_calls, list):
        raise StepExecutionError(
            f"tool_batch step {step.step_id} requires a list of tool calls"
        )
    return [tool_call_from_payload(step, buffer, payload) for payload in raw_calls]


def tool_call_from_payload(
    step: StepSpec,
    buffer: StepScopedDataBufferView,
    payload: Any,
) -> ToolCall:
    if not isinstance(payload, dict):
        raise StepExecutionError(
            f"tool_batch step {step.step_id} tool call must be an object"
        )
    tool_name = str(payload.get("tool_name") or "")
    if not tool_name:
        raise StepExecutionError(
            f"tool_batch step {step.step_id} tool_name is required"
        )
    arguments = payload.get("arguments")
    if "arguments_key" in payload:
        arguments = buffer.read(str(payload["arguments_key"]))
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise StepExecutionError(
            f"tool_batch step {step.step_id} arguments must be an object for {tool_name}"
        )
    call_id = payload.get("call_id")
    requested_by = str(payload.get("requested_by_agent_id") or step.step_id)
    if call_id is None:
        return ToolCall(
            tool_name=tool_name,
            arguments=dict(arguments),
            requested_by_agent_id=requested_by,
        )
    return ToolCall(
        tool_name=tool_name,
        arguments=dict(arguments),
        requested_by_agent_id=requested_by,
        call_id=str(call_id),
    )


def tool_policy_from_step(step: StepSpec) -> ToolPolicy:
    payload = step.metadata.get("tool_policy") or {}
    if not isinstance(payload, dict):
        raise StepExecutionError(
            f"tool_batch step {step.step_id} tool_policy must be an object"
        )
    return ToolPolicy(
        allowed_tools=[
            str(tool_name) for tool_name in payload.get("allowed_tools", [])
        ],
        blocked_tools=[
            str(tool_name) for tool_name in payload.get("blocked_tools", [])
        ],
        allow_mcp_tools=bool(payload.get("allow_mcp_tools", False)),
        max_tool_calls_per_iteration=int(
            payload.get("max_tool_calls_per_iteration", 3)
        ),
        max_tool_calls_per_agent=int(payload.get("max_tool_calls_per_agent", 20)),
        require_explicit_allowlist=bool(
            payload.get("require_explicit_allowlist", True)
        ),
        allow_dangerous_tools=bool(payload.get("allow_dangerous_tools", False)),
        require_approval_for_side_effects=bool(
            payload.get("require_approval_for_side_effects", True)
        ),
        max_result_chars_inline=int(payload.get("max_result_chars_inline", 8000)),
        spill_large_results_to_artifact=bool(
            payload.get("spill_large_results_to_artifact", True)
        ),
        timeout_seconds_default=payload.get("timeout_seconds_default", 30.0),
        max_attempts_default=int(payload.get("max_attempts_default", 1)),
        cancellation_grace_seconds=float(
            payload.get("cancellation_grace_seconds", 0.1)
        ),
        max_total_attempts=(
            int(payload["max_total_attempts"])
            if payload.get("max_total_attempts") is not None
            else None
        ),
    )


def tool_call_metrics(observation: Any) -> dict[str, Any]:
    return {
        "tool_name": observation.call.tool_name,
        "tool_call_id": observation.call.call_id,
        "tool_status": observation.status.value,
        "elapsed_ms": observation.elapsed_ms,
        "output_bytes": observation.result.output_bytes,
        "artifact_ref_count": len(observation.result.artifact_refs),
        "approval_required": observation.status.value == "approval_required",
    }


def tool_batch_metrics(observations: list[Any], *, max_workers: int) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    artifact_ref_count = 0
    output_bytes = 0
    for observation in observations:
        status = observation.status.value
        status_counts[status] = status_counts.get(status, 0) + 1
        artifact_ref_count += len(observation.result.artifact_refs)
        if observation.result.output_bytes is not None:
            output_bytes += int(observation.result.output_bytes)
    return {
        "tool_call_count": len(observations),
        "succeeded_count": status_counts.get("succeeded", 0),
        "failed_count": len(observations) - status_counts.get("succeeded", 0),
        "blocked_count": status_counts.get("blocked", 0),
        "approval_required_count": status_counts.get("approval_required", 0),
        "timeout_count": status_counts.get("timeout", 0),
        "status_counts": status_counts,
        "artifact_ref_count": artifact_ref_count,
        "output_bytes": output_bytes,
        "max_workers": max_workers,
    }


def observation_key(step: StepSpec) -> str:
    return str(
        step.metadata.get("observation_key") or f"{step.step_id}_tool_observation"
    )


def result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or f"{step.step_id}_tool_result")


def observations_key(step: StepSpec) -> str:
    return str(step.metadata.get("observations_key") or "tool_observations")


def results_key(step: StepSpec) -> str:
    return str(step.metadata.get("results_key") or "tool_results")
