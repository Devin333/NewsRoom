"""Tool call step runner."""

from __future__ import annotations

import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.tool import ToolExecutor, ToolStatus
from framework.workflow.buffer import StepScopedDataBufferView
from framework.agent.artifacts import ArtifactManager
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._tool_utils import (
    observation_key,
    result_key,
    single_tool_call_from_step,
    tool_call_metrics,
    tool_policy_from_step,
)
from framework.workflow.runners._utils import (
    failed_outcome,
    validated_outputs,
    with_contract_metrics,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
)

TOOL_CALL_STEP_TYPES = {
    StepType.TOOL_CALL,
    StepType.NOTIFICATION,
    StepType.MEMORY_INDEX,
    StepType.PERSIST,
}


class ToolCallStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.TOOL_CALL,
        runner_id="builtin.tool",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=False,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["tool_registry"],
        description="Runs a single ToolRuntime-backed tool step.",
    )

    def __init__(
        self,
        registry: Any,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
        approval_store: Any | None = None,
        secret_provider: Any | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._approval_store = approval_store
        self._secret_provider = secret_provider

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type in TOOL_CALL_STEP_TYPES

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.metadata.get("tool_call") is not None:
            return []
        if step.metadata.get("tool_name") is not None:
            return []
        if step.metadata.get("tool_call_key") is not None:
            return []
        return [
            ValidationErrorItem(
                code="tool_missing_tool_name",
                message="Tool step requires metadata.tool_name, metadata.tool_call, or metadata.tool_call_key.",
                field="metadata.tool_name",
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
            if step.step_type not in TOOL_CALL_STEP_TYPES:
                raise StepExecutionError(
                    f"unsupported step type for ToolCallStepRunner: {step.step_type}"
                )

            call = single_tool_call_from_step(step, buffer)
            policy = tool_policy_from_step(step)
            executor = ToolExecutor(
                self._registry,
                artifact_manager=self._artifact_manager,
                run_id=self._run_id,
                approval_store=self._approval_store,
                secret_provider=self._secret_provider,
            )
            observation = executor.execute(call, policy)
            outputs = validated_outputs(
                step,
                {
                    observation_key(step): observation.to_dict(),
                    result_key(step): observation.result.to_dict(),
                },
                runner_name="tool_call step",
            )
            for key, value in outputs.items():
                if key in buffer.list_allowed_writes():
                    buffer.write(key, value)
            metrics = with_contract_metrics(
                tool_call_metrics(observation),
                step,
                started=started,
                outputs=outputs,
                artifact_count=len(observation.result.artifact_refs),
            )

            if observation.status == ToolStatus.SUCCEEDED:
                return StepOutcome(
                    status=StepStatus.SUCCEEDED, outputs=outputs, metrics=metrics
                )
            if observation.status == ToolStatus.APPROVAL_REQUIRED:
                return StepOutcome(
                    status=StepStatus.PAUSED,
                    outputs=outputs,
                    error_type=observation.result.error_type,
                    error_message=observation.result.error_message,
                    error_details={"approval_id": observation.result.approval_id},
                    metrics=metrics,
                    next_hint="approval_required",
                )
            if observation.status == ToolStatus.BLOCKED:
                return StepOutcome(
                    status=StepStatus.BLOCKED,
                    outputs=outputs,
                    error_type=observation.result.error_type,
                    error_message=observation.result.error_message,
                    metrics=metrics,
                )
            if observation.status == ToolStatus.TIMEOUT:
                return StepOutcome(
                    status=StepStatus.TIMEOUT,
                    outputs=outputs,
                    error_type=observation.result.error_type,
                    error_message=observation.result.error_message,
                    error_details={
                        "termination_confirmed": (
                            observation.result.termination_confirmed
                        ),
                        "indeterminate": observation.result.indeterminate,
                        "attempt_id": observation.result.attempt_id,
                        "idempotency_key": observation.result.idempotency_key,
                        "operation_id": observation.result.operation_id,
                        "local_attempt_no": observation.result.local_attempt_no,
                        "retry_credit_id": observation.result.retry_credit_id,
                    },
                    metrics=metrics,
                )
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs=outputs,
                error_type=observation.result.error_type,
                error_message=observation.result.error_message,
                error_details={
                    "termination_confirmed": (
                        observation.result.termination_confirmed
                    ),
                    "indeterminate": observation.result.indeterminate,
                    "effect_determinacy_confirmed": (
                        observation.result.termination_confirmed is not False
                        and not observation.result.indeterminate
                    ),
                    "attempt_id": observation.result.attempt_id,
                    "idempotency_key": observation.result.idempotency_key,
                    "operation_id": observation.result.operation_id,
                    "local_attempt_no": observation.result.local_attempt_no,
                    "retry_credit_id": observation.result.retry_credit_id,
                },
                metrics=metrics,
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="ToolCallStepRunner",
            )

__all__ = ["ToolCallStepRunner"]
