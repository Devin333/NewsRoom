"""Tool batch step runner."""

from __future__ import annotations

import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.tool import ToolBatchExecutor
from framework.workflow.buffer import StepScopedDataBufferView
from framework.artifacts import ArtifactManager
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._tool_utils import (
    observations_key,
    results_key,
    tool_batch_metrics,
    tool_calls_from_step,
    tool_policy_from_step,
)
from framework.workflow.runners._utils import (
    contract_metrics,
    validated_outputs,
    with_contract_metrics,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    default_runner_can_resolve,
)


class ToolBatchStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.TOOL_BATCH,
        runner_id="builtin.tool_batch",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=False,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["tool_registry"],
        description="Runs batched tool calls through ToolRuntime.",
    )

    def __init__(
        self,
        registry: Any,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
        secret_provider: Any | None = None,
        max_workers: int = 4,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._secret_provider = secret_provider
        self._max_workers = max_workers

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if (
            step.metadata.get("tool_calls") is not None
            or step.metadata.get("tool_calls_key") is not None
        ):
            return []
        return [
            ValidationErrorItem(
                code="tool_batch_missing_tool_calls",
                message="Tool batch step requires metadata.tool_calls or metadata.tool_calls_key.",
                field="metadata.tool_calls",
            )
        ]

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.TOOL_BATCH:
                raise StepExecutionError(
                    f"unsupported step type for ToolBatchStepRunner: {step.step_type}"
                )

            tool_calls = tool_calls_from_step(step, buffer)
            policy = tool_policy_from_step(step)
            executor = ToolBatchExecutor(
                self._registry,
                artifact_manager=self._artifact_manager,
                run_id=self._run_id,
                secret_provider=self._secret_provider,
                max_workers=self._max_workers,
            )
            observations = executor.execute_batch(tool_calls, policy)
            observation_payloads = [
                observation.to_dict() for observation in observations
            ]
            result_payloads = [
                observation.result.to_dict() for observation in observations
            ]
            outputs = validated_outputs(
                step,
                {
                    observations_key(step): observation_payloads,
                    results_key(step): result_payloads,
                },
                runner_name="tool_batch step",
            )
            for key, value in outputs.items():
                buffer.write(key, value)

            metrics = with_contract_metrics(
                tool_batch_metrics(observations, max_workers=self._max_workers),
                step,
                started=started,
                outputs=outputs,
                artifact_count=sum(
                    len(observation.result.artifact_refs)
                    for observation in observations
                ),
            )
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
                    metrics=metrics,
                )
            return StepOutcome(
                status=StepStatus.SUCCEEDED, outputs=outputs, metrics=metrics
            )
        except Exception as exc:
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                metrics=contract_metrics(step, started=started),
            )

__all__ = ["ToolBatchStepRunner"]


