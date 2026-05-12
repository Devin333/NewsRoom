from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from core.framework.specs import StepSpec, StepStatus, StepType
from core.framework.workflow.buffer import ScopedDataBuffer
from core.framework.workflow.result import StepOutcome

FunctionStep = Callable[[ScopedDataBuffer], dict[str, Any] | None]


class StepExecutionError(RuntimeError):
    """Raised when a step cannot be executed by a runner."""


class StepRunner(Protocol):
    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        ...


class StepRunnerRegistry:
    def __init__(self) -> None:
        self._runners: dict[StepType, StepRunner] = {}

    @classmethod
    def with_function_runner(cls, runner: FunctionStepRunner) -> StepRunnerRegistry:
        registry = cls()
        registry.register(StepType.FUNCTION, runner)
        return registry

    def register(self, step_type: StepType | str, runner: StepRunner) -> None:
        actual_step_type = StepType(step_type)
        if actual_step_type in self._runners:
            raise StepExecutionError(f"step runner is already registered: {actual_step_type.value}")
        self._runners[actual_step_type] = runner

    def get(self, step_type: StepType | str) -> StepRunner:
        actual_step_type = StepType(step_type)
        try:
            return self._runners[actual_step_type]
        except KeyError as exc:
            raise StepExecutionError(f"step runner is not registered: {actual_step_type.value}") from exc

    def is_registered(self, step_type: StepType | str) -> bool:
        return StepType(step_type) in self._runners

    def missing_step_types(self, step_types: list[StepType | str]) -> list[StepType]:
        missing = {
            StepType(step_type)
            for step_type in step_types
            if not self.is_registered(step_type)
        }
        return sorted(missing, key=lambda step_type: step_type.value)

    def registered_step_types(self) -> list[StepType]:
        return sorted(self._runners, key=lambda step_type: step_type.value)


class FunctionStepRegistry:
    def __init__(self) -> None:
        self._functions: dict[str, FunctionStep] = {}

    def register(self, implementation: str, function: FunctionStep) -> None:
        if not implementation:
            raise ValueError("implementation is required")
        self._functions[implementation] = function

    def get(self, implementation: str) -> FunctionStep:
        try:
            return self._functions[implementation]
        except KeyError as exc:
            raise StepExecutionError(f"function step is not registered: {implementation}") from exc


class FunctionStepRunner:
    def __init__(self, registry: FunctionStepRegistry) -> None:
        self._registry = registry

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.FUNCTION:
            raise StepExecutionError(f"unsupported step type for FunctionStepRunner: {step.step_type}")

        function = self._registry.get(step.implementation)
        raw_outputs = function(buffer)
        outputs = raw_outputs or {}
        if not isinstance(outputs, dict):
            raise StepExecutionError(
                f"function step {step.step_id} returned {type(outputs).__name__}, expected dict"
            )

        missing = [key for key in step.required_output_keys if key not in outputs]
        if missing:
            raise StepExecutionError(
                f"function step {step.step_id} did not return required output keys: "
                f"{', '.join(sorted(missing))}"
            )

        for key, value in outputs.items():
            buffer.write(key, value)

        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs)


class ToolBatchStepRunner:
    def __init__(
        self,
        registry: Any,
        *,
        max_workers: int = 4,
    ) -> None:
        self._registry = registry
        self._max_workers = max_workers

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.TOOL_BATCH:
            raise StepExecutionError(f"unsupported step type for ToolBatchStepRunner: {step.step_type}")

        tool_calls = _tool_calls_from_step(step, buffer)
        policy = _tool_policy_from_step(step)
        from core.framework.tools import ToolBatchExecutor

        executor = ToolBatchExecutor(self._registry, max_workers=self._max_workers)
        observations = executor.execute_batch(tool_calls, policy)
        observation_payloads = [observation.to_dict() for observation in observations]
        result_payloads = [observation.result.to_dict() for observation in observations]
        outputs = {
            _observations_key(step): observation_payloads,
            _results_key(step): result_payloads,
        }
        for key, value in outputs.items():
            buffer.write(key, value)

        failed_observations = [
            observation
            for observation in observations
            if observation.status.value != "succeeded"
        ]
        if failed_observations:
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs=outputs,
                error_type="ToolBatchStepFailed",
                error_message=(
                    f"{len(failed_observations)} tool call(s) did not succeed"
                ),
                error_details={
                    "failed_tool_calls": [
                        {
                            "tool_name": observation.call.tool_name,
                            "tool_call_id": observation.call.call_id,
                            "status": observation.status.value,
                            "error_type": observation.result.error_type,
                            "error_message": observation.result.error_message,
                        }
                        for observation in failed_observations
                    ],
                    "tool_call_count": len(observations),
                },
            )
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs)


def _tool_calls_from_step(step: StepSpec, buffer: ScopedDataBuffer) -> list[ToolCall]:
    raw_calls = step.metadata.get("tool_calls")
    if raw_calls is None:
        raw_calls = buffer.read(str(step.metadata.get("tool_calls_key") or "tool_calls"))
    if not isinstance(raw_calls, list):
        raise StepExecutionError(f"tool_batch step {step.step_id} requires a list of tool calls")
    return [_tool_call_from_payload(step, buffer, payload) for payload in raw_calls]


def _tool_call_from_payload(
    step: StepSpec,
    buffer: ScopedDataBuffer,
    payload: Any,
) -> ToolCall:
    from core.framework.tools import ToolCall

    if not isinstance(payload, dict):
        raise StepExecutionError(f"tool_batch step {step.step_id} tool call must be an object")
    tool_name = str(payload.get("tool_name") or "")
    if not tool_name:
        raise StepExecutionError(f"tool_batch step {step.step_id} tool_name is required")
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


def _tool_policy_from_step(step: StepSpec) -> ToolPolicy:
    from core.framework.tools import ToolPolicy

    payload = step.metadata.get("tool_policy") or {}
    if not isinstance(payload, dict):
        raise StepExecutionError(f"tool_batch step {step.step_id} tool_policy must be an object")
    return ToolPolicy(
        allowed_tools=[str(tool_name) for tool_name in payload.get("allowed_tools", [])],
        blocked_tools=[str(tool_name) for tool_name in payload.get("blocked_tools", [])],
        allow_mcp_tools=bool(payload.get("allow_mcp_tools", False)),
        max_tool_calls_per_iteration=int(payload.get("max_tool_calls_per_iteration", 3)),
        max_tool_calls_per_agent=int(payload.get("max_tool_calls_per_agent", 20)),
        require_explicit_allowlist=bool(payload.get("require_explicit_allowlist", True)),
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
    )


def _observations_key(step: StepSpec) -> str:
    return str(step.metadata.get("observations_key") or "tool_observations")


def _results_key(step: StepSpec) -> str:
    return str(step.metadata.get("results_key") or "tool_results")
