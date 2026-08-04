from __future__ import annotations

import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.agent.artifacts import ArtifactManager
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._memory_utils import (
    memory_actor_from_step,
    memory_consolidate_result_key,
    memory_consolidation_request_from_step,
    memory_context_key,
    memory_query_from_step,
    memory_recall_result_key,
    memory_records_from_step,
    memory_records_key,
    memory_write_result_key,
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
    default_runner_can_resolve,
)


class MemoryRecallStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.MEMORY_RECALL,
        runner_id="builtin.memory_recall",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.READ_ONLY,
        required_dependencies=["memory_runtime"],
        description="Runs a direct MemoryRuntime recall step.",
    )

    def __init__(self, memory_runtime: Any | None) -> None:
        self._memory_runtime = memory_runtime
        self._run_id: str | None = None

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if (
            step.metadata.get("query") is not None
            or step.metadata.get("query_key") is not None
        ):
            return []
        return [
            ValidationErrorItem(
                code="memory_recall_missing_query",
                message="Memory recall step requires metadata.query or metadata.query_key.",
                field="metadata.query",
            )
        ]

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.MEMORY_RECALL:
                raise StepExecutionError(
                    f"unsupported step type for MemoryRecallStepRunner: {step.step_type}"
                )
            if self._memory_runtime is None:
                raise StepExecutionError("memory runtime is not configured")

            query = memory_query_from_step(step, buffer)
            recall_result = self._memory_runtime.recall(query)
            result_payload = recall_result.to_dict()
            context_payload = recall_result.context_block.to_dict()
            records_payload = [result.to_dict() for result in recall_result.results]
            outputs = validated_outputs(
                step,
                {
                    memory_recall_result_key(step): result_payload,
                    memory_context_key(step): context_payload,
                    memory_records_key(step): records_payload,
                },
                runner_name="memory_recall step",
            )
            for key, value in outputs.items():
                buffer.write(
                    key,
                    value,
                    lineage={
                        "step_id": step.step_id,
                        "runner_id": self.capability.runner_id,
                        "run_id": self._run_id,
                    },
                )

            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=with_contract_metrics(
                    {
                        "memory_operation": {
                            "operation": "recall",
                            "result_count": recall_result.result_count,
                            "memory_ids": list(recall_result.context_block.memory_ids),
                            "context_token_estimate": recall_result.context_block.token_estimate,
                        },
                        "memory_result_count": recall_result.result_count,
                        "memory_context_token_estimate": recall_result.context_block.token_estimate,
                    },
                    step,
                    started=started,
                    outputs=outputs,
                ),
                lineage=[
                    {
                        "event_type": "memory_recall",
                        "step_id": step.step_id,
                        "run_id": self._run_id,
                        "memory_ids": list(recall_result.context_block.memory_ids),
                        "result_count": recall_result.result_count,
                    }
                ],
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="MemoryRecallStepRunner",
            )


class MemoryWriteStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.MEMORY_WRITE,
        runner_id="builtin.memory_write",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["memory_runtime"],
        description="Runs a direct MemoryRuntime write step.",
    )

    def __init__(
        self, memory_runtime: Any | None, *, run_id: str | None = None
    ) -> None:
        self._memory_runtime = memory_runtime
        self._run_id = run_id

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if (
            step.metadata.get("records") is not None
            or step.metadata.get("records_key") is not None
        ):
            return []
        return [
            ValidationErrorItem(
                code="memory_write_missing_records",
                message="Memory write step requires metadata.records or metadata.records_key.",
                field="metadata.records",
            )
        ]

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.MEMORY_WRITE:
                raise StepExecutionError(
                    f"unsupported step type for MemoryWriteStepRunner: {step.step_type}"
                )
            if self._memory_runtime is None:
                raise StepExecutionError("memory runtime is not configured")

            records = memory_records_from_step(step, buffer)
            write_result = self._memory_runtime.write(
                records=records,
                mode=str(step.metadata.get("mode") or "append"),
                actor=memory_actor_from_step(step, buffer),
                run_id=self._run_id,
            )
            result_payload = write_result.to_dict()
            outputs = validated_outputs(
                step,
                {memory_write_result_key(step): result_payload},
                runner_name="memory_write step",
            )
            for key, value in outputs.items():
                buffer.write(
                    key,
                    value,
                    lineage={
                        "step_id": step.step_id,
                        "runner_id": self.capability.runner_id,
                        "run_id": self._run_id,
                    },
                )

            metrics = with_contract_metrics(
                {
                    "memory_operation": {
                        "operation": "write",
                        "accepted_count": write_result.accepted_count,
                        "written_count": write_result.written_count,
                        "skipped_count": write_result.skipped_count,
                        "memory_ids": list(write_result.memory_ids),
                    },
                    "memory_accepted_count": write_result.accepted_count,
                    "memory_written_count": write_result.written_count,
                    "memory_skipped_count": write_result.skipped_count,
                },
                step,
                started=started,
                outputs=outputs,
            )
            if not write_result.success:
                return StepOutcome(
                    status=StepStatus.FAILED,
                    outputs=outputs,
                    error_type="MemoryWriteFailed",
                    error_message="memory write failed",
                    error_details={"errors": list(write_result.errors)},
                    metrics=metrics,
                    lineage=[
                        {
                            "event_type": "memory_write",
                            "step_id": step.step_id,
                            "run_id": self._run_id,
                            "memory_ids": list(write_result.memory_ids),
                            "accepted_count": write_result.accepted_count,
                            "written_count": write_result.written_count,
                            "skipped_count": write_result.skipped_count,
                        }
                    ],
                )
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=metrics,
                lineage=[
                    {
                        "event_type": "memory_write",
                        "step_id": step.step_id,
                        "run_id": self._run_id,
                        "memory_ids": list(write_result.memory_ids),
                        "accepted_count": write_result.accepted_count,
                        "written_count": write_result.written_count,
                        "skipped_count": write_result.skipped_count,
                    }
                ],
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="MemoryWriteStepRunner",
            )


class MemoryConsolidateStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.MEMORY_CONSOLIDATE,
        runner_id="builtin.memory_consolidate",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["memory_runtime"],
        description="Runs a direct MemoryRuntime consolidation step.",
    )

    def __init__(
        self, memory_runtime: Any | None, *, run_id: str | None = None
    ) -> None:
        self._memory_runtime = memory_runtime
        self._run_id = run_id

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if (
            step.metadata.get("memory_ids") is not None
            or step.metadata.get("memory_ids_key") is not None
            or step.metadata.get("query") is not None
            or step.metadata.get("query_key") is not None
            or step.metadata.get("filters") is not None
            or step.metadata.get("filters_key") is not None
        ):
            return []
        return [
            ValidationErrorItem(
                code="memory_consolidate_missing_selection",
                message=(
                    "Memory consolidate step requires metadata.memory_ids, "
                    "metadata.memory_ids_key, metadata.query, metadata.query_key, "
                    "metadata.filters, or metadata.filters_key."
                ),
                field="metadata",
            )
        ]

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.MEMORY_CONSOLIDATE:
                raise StepExecutionError(
                    f"unsupported step type for MemoryConsolidateStepRunner: {step.step_type}"
                )
            if self._memory_runtime is None:
                raise StepExecutionError("memory runtime is not configured")

            request = memory_consolidation_request_from_step(
                step,
                buffer,
                run_id=self._run_id,
            )
            result = self._memory_runtime.consolidate(request.to_dict())
            result_payload = result.to_dict()
            outputs = validated_outputs(
                step,
                {memory_consolidate_result_key(step): result_payload},
                runner_name="memory_consolidate step",
            )
            for key, value in outputs.items():
                buffer.write(
                    key,
                    value,
                    lineage={
                        "step_id": step.step_id,
                        "runner_id": self.capability.runner_id,
                        "run_id": self._run_id,
                    },
                )

            metrics = with_contract_metrics(
                {
                    "memory_operation": {
                        "operation": "consolidate",
                        "consolidated_count": result.consolidated_count,
                        "skipped_count": result.skipped_count,
                        "memory_ids": list(result.memory_ids),
                        "source_memory_ids": list(result.source_memory_ids),
                    },
                    "memory_consolidated_count": result.consolidated_count,
                    "memory_skipped_count": result.skipped_count,
                },
                step,
                started=started,
                outputs=outputs,
            )
            if not result.success:
                return StepOutcome(
                    status=StepStatus.FAILED,
                    outputs=outputs,
                    error_type="MemoryConsolidateFailed",
                    error_message="memory consolidation failed",
                    error_details={"warnings": list(result.warnings)},
                    metrics=metrics,
                    lineage=[
                        {
                            "event_type": "memory_consolidate",
                            "step_id": step.step_id,
                            "run_id": self._run_id,
                            "memory_ids": list(result.memory_ids),
                            "source_memory_ids": list(result.source_memory_ids),
                            "consolidated_count": result.consolidated_count,
                            "skipped_count": result.skipped_count,
                        }
                    ],
                )
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=metrics,
                lineage=[
                    {
                        "event_type": "memory_consolidate",
                        "step_id": step.step_id,
                        "run_id": self._run_id,
                        "memory_ids": list(result.memory_ids),
                        "source_memory_ids": list(result.source_memory_ids),
                        "consolidated_count": result.consolidated_count,
                        "skipped_count": result.skipped_count,
                    }
                ],
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="MemoryConsolidateStepRunner",
            )


__all__ = [
    "MemoryConsolidateStepRunner",
    "MemoryRecallStepRunner",
    "MemoryWriteStepRunner",
]
