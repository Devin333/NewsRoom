from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from hashlib import sha256
import json
import re
import time
from typing import TYPE_CHECKING, Any

from framework.workflow.runtime.artifacts import ArtifactManager
from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.runtime.workflow_artifacts import LocalArtifactPublisher
from framework.workflow.buffer import DataBuffer, StepScopedDataBufferView
from framework.workflow.runners.human_review import (
    HumanReviewRequest,
    human_review_expires_at,
    human_review_request_id,
    utc_now_iso as human_review_utc_now_iso,
)
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunner,  # noqa: F401 - re-exported from framework.workflow
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    default_runner_can_resolve,
)
from framework.workflow.runners.memory_models import (
    MemoryConsolidationRequest,
    MemoryQuery,
)
from framework.tool import (
    ToolBatchExecutor,
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolStatus,
)
from framework.workflow.runtime.artifacts import ArtifactRef as StorageArtifactRef

if TYPE_CHECKING:
    from framework.specs import WorkflowSpec

FunctionStep = Callable[[StepScopedDataBufferView], dict[str, Any] | None]

_BRANCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_PARALLEL_CONFLICT_STRATEGIES = {
    "error",
    "namespace",
    "last_write",
    # Backward-compatible legacy names.
    "first_wins",
    "last_wins",
    "merge_list",
    "merge_dict",
}
_PARALLEL_FAILURE_STRATEGIES = {
    "fail_fast",
    "best_effort",
    "all_success",
    "min_success",
}


class _ParallelBranchExecutionError(Exception):
    def __init__(self, original_error: Exception, *, attempts: int) -> None:
        super().__init__(str(original_error))
        self.original_error = original_error
        self.attempts = attempts


def build_default_step_runner_registry(
    function_registry: FunctionStepRegistry | None = None,
    *,
    tool_registry: Any | None = None,
    agent_runner: Any | None = None,
    agent_registry: dict[str, Any] | None = None,
    workflow_registry: dict[str, Any] | None = None,
    artifact_manager: ArtifactManager | None = None,
    memory_runtime: Any | None = None,
    run_id: str | None = None,
    approval_store: Any | None = None,
    secret_provider: Any | None = None,
    global_budget_tracker: Any | None = None,
    max_parallel_workers: int = 4,
    max_tool_batch_workers: int = 4,
    available_dependencies: set[str] | None = None,
) -> StepRunnerRegistry:
    """Build the standard runtime registry from explicitly injected dependencies."""

    dependencies = set(available_dependencies or set())
    effective_function_registry = function_registry or FunctionStepRegistry()
    effective_tool_registry = tool_registry
    effective_agent_registry = dict(agent_registry or {})
    effective_workflow_registry = dict(workflow_registry or {})
    if function_registry is not None:
        dependencies.add("function_registry")
    if tool_registry is not None:
        dependencies.add("tool_registry")
    if agent_runner is not None:
        dependencies.add("llm_client")
    if agent_registry:
        dependencies.add("agent_registry")
    if workflow_registry is not None:
        dependencies.add("workflow_executor")
    if artifact_manager is not None:
        dependencies.add("artifact_publisher")
    if memory_runtime is not None:
        dependencies.add("memory_runtime")
    if approval_store is not None:
        dependencies.add("human_review_store")

    registry = StepRunnerRegistry(available_dependencies=dependencies)

    registry.register(FunctionStepRunner(effective_function_registry))
    registry.register(
        ParallelGroupStepRunner(
            effective_function_registry, max_workers=max_parallel_workers
        ),
    )

    tool_call_runner = ToolCallStepRunner(
        effective_tool_registry,
        artifact_manager=artifact_manager,
        run_id=run_id,
        approval_store=approval_store,
        secret_provider=secret_provider,
    )
    registry.register(tool_call_runner)
    for step_type in sorted(
        _TOOL_CALL_STEP_TYPES - {StepType.TOOL_CALL}, key=lambda item: item.value
    ):
        registry.register_alias(step_type, tool_call_runner)
    registry.register(
        ToolBatchStepRunner(
            effective_tool_registry,
            artifact_manager=artifact_manager,
            run_id=run_id,
            secret_provider=secret_provider,
            max_workers=max_tool_batch_workers,
        ),
    )
    registry.register(MemoryRecallStepRunner(memory_runtime))
    registry.register(MemoryWriteStepRunner(memory_runtime, run_id=run_id))
    registry.register(MemoryConsolidateStepRunner(memory_runtime, run_id=run_id))

    registry.register(
        AgentLoopStepRunner(
            agent_runner,
            effective_agent_registry,
            global_budget_tracker=global_budget_tracker,
        ),
    )

    registry.register(RouterStepRunner())
    registry.register(JoinStepRunner())
    registry.register(QualityGateStepRunner())
    registry.register(HumanReviewStepRunner())
    registry.register(ArtifactStepRunner(artifact_manager, run_id=run_id))

    registry.register(
        SubworkflowStepRunner(
            effective_workflow_registry,
            registry,
            artifact_manager=artifact_manager,
            run_id=run_id,
        )
    )

    return registry


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
            raise StepExecutionError(
                f"function step is not registered: {implementation}"
            ) from exc

    def is_registered(self, implementation: str) -> bool:
        return implementation in self._functions


class FunctionStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="builtin.function",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=["function_registry"],
        description="Runs an in-process Python function step.",
    )

    def __init__(self, registry: FunctionStepRegistry) -> None:
        self._registry = registry

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION and self._registry.is_registered(
            step.implementation
        )

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.implementation:
            return []
        return [
            ValidationErrorItem(
                code="function_missing_implementation",
                message="Function step requires implementation.",
                field="implementation",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.FUNCTION:
                raise StepExecutionError(
                    f"unsupported step type for FunctionStepRunner: {step.step_type}"
                )

            function = self._registry.get(step.implementation)
            raw_outputs = function(buffer)
            outputs = _validated_outputs(
                step,
                raw_outputs,
                runner_name="function step",
            )
            for key, value in outputs.items():
                buffer.write(key, value)

            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=_contract_metrics(
                    step,
                    started=started,
                    outputs=outputs,
                ),
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="FunctionStepRunner",
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

            tool_calls = _tool_calls_from_step(step, buffer)
            policy = _tool_policy_from_step(step)
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
            outputs = _validated_outputs(
                step,
                {
                    _observations_key(step): observation_payloads,
                    _results_key(step): result_payloads,
                },
                runner_name="tool_batch step",
            )
            for key, value in outputs.items():
                buffer.write(key, value)

            metrics = _with_contract_metrics(
                _tool_batch_metrics(observations, max_workers=self._max_workers),
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
                metrics=_contract_metrics(step, started=started),
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

            query = _memory_query_from_step(step, buffer)
            recall_result = self._memory_runtime.recall(query)
            result_payload = recall_result.to_dict()
            context_payload = recall_result.context_block.to_dict()
            records_payload = [result.to_dict() for result in recall_result.results]
            outputs = _validated_outputs(
                step,
                {
                    _memory_recall_result_key(step): result_payload,
                    _memory_context_key(step): context_payload,
                    _memory_records_key(step): records_payload,
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
                metrics=_with_contract_metrics(
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
            return _failed_outcome(
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

            records = _memory_records_from_step(step, buffer)
            write_result = self._memory_runtime.write(
                records=records,
                mode=str(step.metadata.get("mode") or "append"),
                actor=_memory_actor_from_step(step, buffer),
                run_id=self._run_id,
            )
            result_payload = write_result.to_dict()
            outputs = _validated_outputs(
                step,
                {_memory_write_result_key(step): result_payload},
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

            metrics = _with_contract_metrics(
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
            return _failed_outcome(
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

            request = _memory_consolidation_request_from_step(
                step,
                buffer,
                run_id=self._run_id,
            )
            result = self._memory_runtime.consolidate(request.to_dict())
            result_payload = result.to_dict()
            outputs = _validated_outputs(
                step,
                {_memory_consolidate_result_key(step): result_payload},
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

            metrics = _with_contract_metrics(
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
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="MemoryConsolidateStepRunner",
            )


class AgentLoopStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.AGENT_LOOP,
        runner_id="builtin.agent_loop",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["llm_client", "agent_registry"],
        description="Runs an AgentLoop step through the configured agent runner.",
    )

    def __init__(
        self,
        agent_runner: Any,
        agent_registry: dict[str, Any],
        global_budget_tracker: Any | None = None,
    ) -> None:
        self._agent_runner = agent_runner
        self._agent_registry = dict(agent_registry)
        self._global_budget_tracker = global_budget_tracker
        self._run_id: str | None = None

    def can_resolve(self, step: StepSpec) -> bool:
        if step.step_type != StepType.AGENT_LOOP:
            return False
        if self._agent_runner is None or not self._agent_registry:
            return True
        agent_id = str(step.metadata.get("agent_id") or step.implementation)
        return agent_id in self._agent_registry

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.metadata.get("agent_id") or step.implementation:
            return []
        return [
            ValidationErrorItem(
                code="agent_loop_missing_agent",
                message="AgentLoop step requires metadata.agent_id or implementation.",
                field="metadata.agent_id",
            )
        ]

    def configure_global_budget_tracker(
        self, global_budget_tracker: Any | None
    ) -> None:
        self._global_budget_tracker = global_budget_tracker

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
        if step.step_type != StepType.AGENT_LOOP:
            return _failed_outcome(
                step,
                StepExecutionError(
                    f"unsupported step type for AgentLoopStepRunner: {step.step_type}"
                ),
                started=started,
                runner_name="AgentLoopStepRunner",
            )

        agent_id = str(step.metadata.get("agent_id") or step.implementation)
        try:
            agent = self._agent_registry[agent_id]
        except KeyError:
            return _failed_outcome(
                step,
                StepExecutionError(f"agent is not registered: {agent_id}"),
                started=started,
                runner_name="AgentLoopStepRunner",
            )

        inputs = {key: buffer.read(key) for key in step.read_keys if buffer.exists(key)}
        conversation_id = step.metadata.get("conversation_id")
        if "conversation_id_key" in step.metadata:
            conversation_id = buffer.read(str(step.metadata["conversation_id_key"]))

        run_kwargs: dict[str, Any] = {
            "conversation_id": str(conversation_id) if conversation_id else None,
            "run_id": self._run_id,
            "step_id": step.step_id,
        }
        if bool(step.metadata.get("resume_from_conversation_cursor")) or bool(
            step.metadata.get("resume_from_cursor")
        ):
            run_kwargs["resume_from_cursor"] = True
        if "workflow_checkpoint_id" in step.metadata:
            run_kwargs["workflow_checkpoint_id"] = str(
                step.metadata["workflow_checkpoint_id"]
            )
        if self._global_budget_tracker is not None:
            run_kwargs["global_budget_tracker"] = self._global_budget_tracker
        result = self._agent_runner.run(agent, inputs, **run_kwargs)
        result_payload = result.to_dict()
        outputs: dict[str, Any] = {}
        if result.success:
            outputs.update(result.output)
        result_key = str(step.metadata.get("result_key") or "agent_loop_result")
        events_key = str(step.metadata.get("events_key") or "agent_loop_events")
        metrics_key = str(step.metadata.get("metrics_key") or "agent_loop_metrics")
        diagnostics_key = str(
            step.metadata.get("diagnostics_key") or "agent_loop_diagnostics"
        )
        trace_key = str(step.metadata.get("trace_key") or "agent_loop_trace")
        trajectory_key = str(
            step.metadata.get("trajectory_key") or "agent_loop_trajectory"
        )
        termination_key = str(
            step.metadata.get("termination_key") or "agent_loop_termination_reason"
        )
        max_steps_key = str(
            step.metadata.get("max_steps_key") or "agent_loop_max_steps_reached"
        )
        llm_artifacts_key = str(
            step.metadata.get("llm_artifacts_key") or "llm_call_artifacts"
        )
        outputs[result_key] = result_payload
        outputs[events_key] = result.events
        outputs[metrics_key] = result.metrics.to_dict()
        outputs[diagnostics_key] = (
            result.diagnostics.to_dict() if result.diagnostics is not None else None
        )
        outputs[trace_key] = result.trace
        outputs[trajectory_key] = [dict(item) for item in result_payload.get("trajectory") or []]
        outputs[termination_key] = result.termination_reason
        outputs[max_steps_key] = result.max_steps_reached
        outputs[llm_artifacts_key] = [
            artifact.to_dict() for artifact in result.llm_call_artifacts
        ]
        declared_outputs = _validated_outputs(
            step,
            outputs,
            runner_name="agent_loop step",
            allow_extra=True,
            allow_missing_required=not result.success,
        )

        for key, value in outputs.items():
            if key in buffer.list_allowed_writes():
                buffer.write(
                    key, value, lineage={"step_id": step.step_id, "agent_id": agent_id}
                )

        status_value = str(result.status.value)
        if result.success:
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=declared_outputs,
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        if status_value == "waiting_for_approval":
            return StepOutcome(
                status=StepStatus.PAUSED,
                outputs=declared_outputs,
                error_type="AgentLoopWaitingForApproval",
                error_message=result.error
                or f"agent loop waiting for approval: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        if status_value == "stalled":
            return StepOutcome(
                status=StepStatus.BLOCKED,
                outputs=declared_outputs,
                error_type="AgentLoopStalled",
                error_message=result.error or f"agent loop stalled: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        if status_value == "blocked":
            return StepOutcome(
                status=StepStatus.BLOCKED,
                outputs=declared_outputs,
                error_type="AgentLoopBlocked",
                error_message=result.error or f"agent loop blocked: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        return StepOutcome(
            status=StepStatus.FAILED,
            outputs=declared_outputs,
            error_type="AgentLoopFailed",
            error_message=result.error or f"agent loop failed: {agent_id}",
            error_details=_agent_loop_error_details(result_payload),
            metrics=_with_contract_metrics(
                _agent_loop_metrics_payload(result),
                step,
                started=started,
                outputs=declared_outputs,
                artifact_count=len(result.llm_call_artifacts),
            ),
            trace_events=_agent_loop_trace_events(result),
        )


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
        return step.step_type in _TOOL_CALL_STEP_TYPES

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
            if step.step_type not in _TOOL_CALL_STEP_TYPES:
                raise StepExecutionError(
                    f"unsupported step type for ToolCallStepRunner: {step.step_type}"
                )

            call = _single_tool_call_from_step(step, buffer)
            policy = _tool_policy_from_step(step)
            executor = ToolExecutor(
                self._registry,
                artifact_manager=self._artifact_manager,
                run_id=self._run_id,
                approval_store=self._approval_store,
                secret_provider=self._secret_provider,
            )
            observation = executor.execute(call, policy)
            outputs = _validated_outputs(
                step,
                {
                    _observation_key(step): observation.to_dict(),
                    _result_key(step): observation.result.to_dict(),
                },
                runner_name="tool_call step",
            )
            for key, value in outputs.items():
                if key in buffer.list_allowed_writes():
                    buffer.write(key, value)
            metrics = _with_contract_metrics(
                _tool_call_metrics(observation),
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
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs=outputs,
                error_type=observation.result.error_type,
                error_message=observation.result.error_message,
                metrics=metrics,
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="ToolCallStepRunner",
            )


class ParallelGroupStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.PARALLEL_GROUP,
        runner_id="builtin.parallel_group",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=["function_registry"],
        description="Runs in-process function branches concurrently.",
    )

    def __init__(
        self,
        function_registry: FunctionStepRegistry,
        *,
        max_workers: int = 4,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
    ) -> None:
        self._function_registry = function_registry
        self._max_workers = max(1, max_workers)
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        branches = step.metadata.get("branches")
        if isinstance(branches, list) and branches:
            return []
        return [
            ValidationErrorItem(
                code="parallel_group_missing_branches",
                message="Parallel group step requires non-empty metadata.branches.",
                field="metadata.branches",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.PARALLEL_GROUP:
                raise StepExecutionError(
                    f"unsupported step type for ParallelGroupStepRunner: {step.step_type}"
                )
            branches = step.metadata.get("branches")
            if not isinstance(branches, list) or not branches:
                raise StepExecutionError(
                    f"parallel_group step {step.step_id} requires branches"
                )
            normalized_branches = _normalize_parallel_branches(
                branches, step_id=step.step_id
            )

            branch_results: list[dict[str, Any]] = []
            failed_branch_results: list[dict[str, Any]] = []
            merged_outputs: dict[str, Any] = {}
            conflict_strategy = str(step.metadata.get("conflict_strategy") or "error")
            failure_strategy = str(step.metadata.get("failure_strategy") or "fail_fast")
            if conflict_strategy not in _PARALLEL_CONFLICT_STRATEGIES:
                raise StepExecutionError(
                    f"unsupported parallel conflict strategy: {conflict_strategy}"
                )
            if failure_strategy not in _PARALLEL_FAILURE_STRATEGIES:
                raise StepExecutionError(
                    f"unsupported parallel failure strategy: {failure_strategy}"
                )
            min_success = int(
                step.metadata.get("min_success")
                or step.metadata.get("success_threshold")
                or 1
            )
            namespace_key = str(step.metadata.get("namespace_key") or "")
            max_workers = min(self._max_workers, len(normalized_branches))
            pool = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="news-workflow-parallel",
            )
            try:
                branch_results, failed_branch_results = (
                    _run_parallel_branches_with_policy(
                        pool=pool,
                        registry=self._function_registry,
                        branches=normalized_branches,
                        parent_buffer=buffer,
                        failure_strategy=failure_strategy,
                    )
                )
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            _enforce_parallel_failure_strategy(
                failure_strategy=failure_strategy,
                branch_results=branch_results,
                failed_branch_results=failed_branch_results,
                min_success=min_success,
            )
            if conflict_strategy == "namespace":
                namespace_key = namespace_key or "branches"
            else:
                for branch_result in branch_results:
                    _merge_parallel_outputs(
                        merged_outputs,
                        branch_result["outputs"],
                        conflict_strategy=conflict_strategy,
                        step_id=step.step_id,
                    )

            branch_artifacts = _publish_parallel_branch_artifacts(
                artifact_manager=self._artifact_manager,
                run_id=self._run_id,
                step=step,
                branch_results=branch_results,
                failed_branch_results=failed_branch_results,
            )
            outputs = _parallel_group_outputs(
                step,
                merged_outputs=merged_outputs,
                branch_results=branch_results,
                failed_branch_results=failed_branch_results,
                namespace_key=namespace_key,
            )
            outputs = _validated_outputs(
                step, outputs, runner_name="parallel_group step"
            )
            for key, value in outputs.items():
                if key in buffer.list_allowed_writes():
                    buffer.write(
                        key,
                        value,
                        lineage={"step_id": step.step_id, "parallel_group": True},
                    )
            metrics = _with_contract_metrics(
                _parallel_group_metrics(
                    branches=normalized_branches,
                    branch_results=branch_results,
                    failed_branch_results=failed_branch_results,
                    conflict_strategy=conflict_strategy,
                    failure_strategy=failure_strategy,
                    min_success=min_success,
                    max_workers=self._max_workers,
                    output_keys=list(outputs),
                ),
                step,
                started=started,
                outputs=outputs,
            )
            if failed_branch_results and failure_strategy == "best_effort":
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    error_type="ParallelGroupPartialFailure",
                    error_message=(
                        f"{len(failed_branch_results)} parallel branch(es) failed"
                    ),
                    error_details={"failed_branches": failed_branch_results},
                    metrics=metrics,
                    artifacts=branch_artifacts,
                    lineage=_parallel_group_lineage(step, branch_results),
                    next_hint="best_effort",
                )
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=metrics,
                artifacts=branch_artifacts,
                lineage=_parallel_group_lineage(step, branch_results),
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="ParallelGroupStepRunner",
            )


class SubworkflowStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.SUBWORKFLOW,
        runner_id="builtin.subworkflow",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["workflow_executor"],
        description="Runs a child WorkflowSpec as a subworkflow.",
    )

    def __init__(
        self,
        workflow_registry: dict[str, Any],
        step_runner_registry: StepRunnerRegistry,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
    ) -> None:
        self._workflow_registry = dict(workflow_registry)
        self._step_runner_registry = step_runner_registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._global_budget_tracker: Any | None = None

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def configure_global_budget_tracker(
        self, global_budget_tracker: Any | None
    ) -> None:
        self._global_budget_tracker = global_budget_tracker

    def can_resolve(self, step: StepSpec) -> bool:
        if step.step_type != StepType.SUBWORKFLOW:
            return False
        if not self._workflow_registry:
            return True
        workflow_id = str(step.metadata.get("workflow_id") or step.implementation)
        return workflow_id in self._workflow_registry

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.metadata.get("workflow_id") or step.implementation:
            return []
        return [
            ValidationErrorItem(
                code="subworkflow_missing_workflow_id",
                message="Subworkflow step requires metadata.workflow_id or implementation.",
                field="metadata.workflow_id",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.SUBWORKFLOW:
                raise StepExecutionError(
                    f"unsupported step type for SubworkflowStepRunner: {step.step_type}"
                )
            if self._artifact_manager is None or self._run_id is None:
                raise StepExecutionError("SubworkflowStepRunner requires run context")
            parent_run_id = self._run_id

            workflow_id = str(step.metadata.get("workflow_id") or step.implementation)
            try:
                workflow = self._workflow_registry[workflow_id]
            except KeyError as exc:
                raise StepExecutionError(
                    f"subworkflow is not registered: {workflow_id}"
                ) from exc

            request = _subworkflow_request(step, buffer)

            from framework.workflow.runtime.executor import WorkflowExecutor

            child_run_id = str(
                step.metadata.get("child_run_id")
                or f"{self._run_id}.{step.step_id}.{workflow.workflow_id}"
            )
            executor = WorkflowExecutor(
                function_step_runner=None,
                step_runner_registry=self._step_runner_registry,
                artifact_manager=self._artifact_manager,
                global_budget_tracker=(
                    self._global_budget_tracker
                    if _subworkflow_inherits_budget(step)
                    else None
                ),
            )
            result = executor.execute(
                workflow,
                request,
                profile=str(step.metadata.get("profile") or "subworkflow"),
                run_id=child_run_id,
            )
            _record_child_manifest_parent_link(
                artifact_manager=self._artifact_manager,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                parent_step_id=step.step_id,
            )
            metrics = _subworkflow_metrics(
                child_run_id=child_run_id,
                workflow_id=workflow.workflow_id,
                workflow_version=workflow.version,
                result=result,
            )
            metrics["failure_propagation"] = _subworkflow_failure_propagation(step)
            metrics["budget_scope"] = _subworkflow_budget_scope(step)
            metrics["inherit_budget"] = _subworkflow_inherits_budget(step)
            metrics["cancellation_policy"] = _subworkflow_cancellation_policy(step)
            output_key = str(step.metadata.get("output_key") or "subworkflow_result")
            child_run_record = _subworkflow_child_run_record(
                step=step,
                child_run_id=child_run_id,
                workflow=workflow,
                result=result,
            )
            raw_outputs = {
                output_key: result.to_dict(),
                **_subworkflow_optional_outputs(
                    step=step,
                    child_run_record=child_run_record,
                    result=result,
                ),
                **_subworkflow_mapped_outputs(step, result.output),
            }
            if result.status.value != "succeeded":
                raw_outputs.update(
                    _subworkflow_failure_policy_outputs(
                        step=step,
                        result=result,
                    )
                )
            outputs = _validated_outputs(
                step,
                raw_outputs,
                runner_name="subworkflow step",
                allow_missing_required=result.status.value != "succeeded",
            )
            for key, value in outputs.items():
                if key in buffer.list_allowed_writes():
                    buffer.write(key, value, lineage={"step_id": step.step_id})
            metrics = _with_contract_metrics(
                metrics,
                step,
                started=started,
                outputs=outputs,
                artifact_count=int(metrics.get("child_artifact_count") or 0),
            )
            lineage = [
                {
                    "type": "subworkflow",
                    "parent_run_id": self._run_id,
                    "child_run_id": child_run_id,
                    "workflow_id": workflow.workflow_id,
                    "workflow_version": workflow.version,
                    "manifest_path": result.manifest_path,
                    "cancellation_policy": _subworkflow_cancellation_policy(step),
                }
            ]
            if result.status.value == "succeeded":
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    metrics=metrics,
                    lineage=lineage,
                )
            return _subworkflow_failure_outcome(
                step=step,
                workflow_id=workflow_id,
                result=result,
                outputs=outputs,
                metrics=metrics,
                lineage=lineage,
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="SubworkflowStepRunner",
            )


class RouterStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.ROUTER,
        runner_id="builtin.router",
        version="1.0.0",
        supports_checkpoint=False,
        supports_resume=True,
        supports_timeout=False,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=[],
        description="Selects a deterministic route hint.",
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.ROUTER:
                raise StepExecutionError(
                    f"unsupported step type for RouterStepRunner: {step.step_type}"
                )

            route = step.metadata.get("route")
            if route is None:
                route_key = str(step.metadata.get("route_key") or "route")
                route = buffer.read(route_key)
            route = str(route)
            output_key = str(step.metadata.get("output_key") or "route")
            outputs = _validated_outputs(
                step, {output_key: route}, runner_name="router step"
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, route)
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=_contract_metrics(step, started=started, outputs=outputs),
                next_hint=route,
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="RouterStepRunner",
            )


class JoinStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.JOIN,
        runner_id="builtin.join",
        version="1.0.0",
        supports_checkpoint=False,
        supports_resume=True,
        supports_timeout=False,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=[],
        description="Summarizes declared fan-in inputs.",
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.JOIN:
                raise StepExecutionError(
                    f"unsupported step type for JoinStepRunner: {step.step_type}"
                )

            output_key = str(step.metadata.get("output_key") or "join_result")
            inputs = {
                key: buffer.read(key)
                for key in buffer.list_allowed_reads()
                if buffer.exists(key)
            }
            summary = _join_summary(step, inputs)
            outputs = _validated_outputs(
                step,
                {output_key: summary},
                runner_name="join step",
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, outputs[output_key])
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=_contract_metrics(step, started=started, outputs=outputs),
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="JoinStepRunner",
            )


class QualityGateStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.QUALITY_GATE,
        runner_id="builtin.quality_gate",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=[],
        description="Evaluates deterministic report quality gate rules.",
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.QUALITY_GATE:
                raise StepExecutionError(
                    f"unsupported step type for QualityGateStepRunner: {step.step_type}"
                )

            policy = step.quality_policy
            min_citation_coverage = _metadata_float(
                step,
                "min_citation_coverage",
                policy.min_citation_coverage if policy else None,
            )
            min_editor_score = _metadata_float(
                step,
                "min_editor_score",
                policy.min_editor_score if policy else None,
            )
            citation_coverage = _buffer_metric(
                buffer, step, "citation_coverage", "citation_coverage_score"
            )
            editor_score = _buffer_metric(buffer, step, "editor_score", "editor_score")
            unsupported_claims = _buffer_value(
                buffer, step.metadata.get("unsupported_claims_key"), []
            )

            blocked_reasons: list[str] = []
            rewrite_reasons: list[str] = []
            if min_citation_coverage is not None and (
                citation_coverage is None or citation_coverage < min_citation_coverage
            ):
                rewrite_reasons.append("citation_coverage_below_threshold")
            if min_editor_score is not None and (
                editor_score is None or editor_score < min_editor_score
            ):
                rewrite_reasons.append("editor_score_below_threshold")
            if (
                policy is not None
                and policy.block_on_unsupported_claims
                and unsupported_claims
            ):
                blocked_reasons.append("unsupported_claims")

            if blocked_reasons:
                decision = "blocked"
            elif rewrite_reasons:
                decision = "rewrite_required"
            else:
                decision = "pass"

            output_key = str(step.metadata.get("output_key") or "quality_gate_metrics")
            quality_metrics = {
                "decision": decision,
                "citation_coverage": citation_coverage,
                "editor_score": editor_score,
                "blocked_reasons": blocked_reasons,
                "rewrite_reasons": rewrite_reasons,
            }
            outputs = _validated_outputs(
                step,
                {output_key: quality_metrics},
                runner_name="quality_gate step",
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, quality_metrics)
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=_contract_metrics(step, started=started, outputs=outputs),
                next_hint=decision,
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="QualityGateStepRunner",
            )


class HumanReviewStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.HUMAN_REVIEW,
        runner_id="builtin.human_review",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["human_review_store"],
        description="Creates or consumes a human review pause boundary.",
    )

    def __init__(self) -> None:
        self._run_id: str | None = None
        self._workflow_id: str | None = None
        self._workflow_version: str | None = None

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def configure_workflow_context(self, *, workflow: WorkflowSpec) -> None:
        self._workflow_id = workflow.workflow_id
        self._workflow_version = workflow.version

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.HUMAN_REVIEW:
                raise StepExecutionError(
                    f"unsupported step type for HumanReviewStepRunner: {step.step_type}"
                )

            decision_key = str(
                step.metadata.get("decision_key") or "human_review_decision"
            )
            if decision_key in buffer.list_allowed_reads() and buffer.exists(
                decision_key
            ):
                decision = buffer.read(decision_key)
                outputs = _validated_outputs(
                    step,
                    {decision_key: decision},
                    runner_name="human_review step",
                    allow_extra=True,
                )
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    metrics=_contract_metrics(step, started=started, outputs=outputs),
                    next_hint=_human_next_hint(decision),
                )

            request_key = str(
                step.metadata.get("request_key") or "human_review_request"
            )
            created_at = human_review_utc_now_iso()
            checkpoint_id = _optional_metadata_str(step.metadata.get("checkpoint_id"))
            run_id = (
                self._run_id
                or _optional_metadata_str(step.metadata.get("run_id"))
                or "unknown-run"
            )
            request_id = human_review_request_id(
                run_id=run_id,
                step_id=step.step_id,
                checkpoint_id=checkpoint_id,
            )
            request_metadata = {
                **dict(step.metadata.get("request_metadata") or {}),
                "approval_id": str(step.metadata.get("approval_id") or request_id),
                "implementation": step.implementation,
            }
            request = HumanReviewRequest(
                request_id=request_id,
                run_id=run_id,
                step_id=step.step_id,
                workflow_id=(
                    self._workflow_id
                    or _optional_metadata_str(step.metadata.get("workflow_id"))
                    or "unknown-workflow"
                ),
                workflow_version=(
                    self._workflow_version
                    or _optional_metadata_str(step.metadata.get("workflow_version"))
                    or "unknown-version"
                ),
                checkpoint_id=checkpoint_id,
                review_type=str(step.metadata.get("review_type") or "human_review"),
                required_role=_optional_metadata_str(
                    step.metadata.get("required_role")
                ),
                created_at=created_at,
                expires_at=human_review_expires_at(
                    created_at=created_at,
                    timeout_seconds=step.metadata.get("review_timeout_seconds"),
                ),
                inputs={
                    key: buffer.read(key)
                    for key in buffer.list_allowed_reads()
                    if key != decision_key and buffer.exists(key)
                },
                metadata=request_metadata,
            ).to_dict()
            outputs = _validated_outputs(
                step,
                {request_key: request},
                runner_name="human_review step",
            )
            if request_key in buffer.list_allowed_writes():
                buffer.write(request_key, request)
            return StepOutcome(
                status=StepStatus.PAUSED,
                outputs=outputs,
                metrics=_contract_metrics(step, started=started, outputs=outputs),
                next_hint="human_review",
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="HumanReviewStepRunner",
            )


class ArtifactStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.ARTIFACT,
        runner_id="builtin.artifact",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["artifact_publisher"],
        description="Writes a workflow artifact through ArtifactManager.",
    )

    def __init__(
        self,
        artifact_manager: ArtifactManager | None = None,
        *,
        run_id: str | None = None,
        artifact_publisher: Any | None = None,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._artifact_publisher = artifact_publisher

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        if self._artifact_publisher is None:
            self._artifact_publisher = LocalArtifactPublisher(artifact_manager.root)

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if (
            step.metadata.get("content") is not None
            or step.metadata.get("content_key") is not None
        ):
            return []
        return [
            ValidationErrorItem(
                code="artifact_missing_content",
                message="Artifact step requires metadata.content or metadata.content_key.",
                field="metadata.content",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.ARTIFACT:
                raise StepExecutionError(
                    f"unsupported step type for ArtifactStepRunner: {step.step_type}"
                )
            if self._artifact_manager is None or self._run_id is None:
                raise StepExecutionError("ArtifactStepRunner requires run context")
            if self._artifact_publisher is None:
                self._artifact_publisher = LocalArtifactPublisher(
                    self._artifact_manager.root
                )

            content = step.metadata.get("content")
            content_key = step.metadata.get("content_key")
            if content_key is not None:
                content = buffer.read(str(content_key))
            relative_path = str(
                step.metadata.get("relative_path")
                or f"steps/{step.step_id}/output.json"
            )
            content_type = str(step.metadata.get("content_type") or "application/json")
            artifact_type = str(step.metadata.get("artifact_type") or "step_output")
            artifact_id = str(
                step.metadata.get("artifact_id") or f"{step.step_id}:{artifact_type}"
            )
            output_key = str(step.metadata.get("output_key") or "artifact_ref")

            if content_type == "text/plain" or relative_path.endswith((".md", ".txt")):
                data = str(content).encode("utf-8")
            else:
                data = _json_artifact_bytes(content)

            publish_result = self._artifact_publisher.publish_artifact(
                run_id=self._run_id,
                step_id=step.step_id,
                key=output_key,
                artifact_type=artifact_type,
                content=data,
                metadata={
                    "artifact_id": artifact_id,
                    "relative_path": relative_path,
                    "content_type": content_type,
                    **dict(step.metadata.get("artifact_metadata") or {}),
                },
            )
            if not publish_result.succeeded or publish_result.artifact_ref is None:
                raise StepExecutionError(
                    publish_result.error or "artifact publish failed"
                )

            workflow_artifact_ref = publish_result.artifact_ref
            artifact_ref = StorageArtifactRef(
                artifact_id=artifact_id,
                run_id=self._run_id,
                step_id=step.step_id,
                artifact_type=artifact_type,
                path=workflow_artifact_ref.uri,
                content_type=content_type,
                size_bytes=workflow_artifact_ref.size_bytes,
                checksum=workflow_artifact_ref.content_hash,
                redacted=bool(step.metadata.get("redacted", True)),
                metadata={
                    "artifact_key": output_key,
                    "workflow_artifact_ref": workflow_artifact_ref.to_dict(),
                },
            )
            outputs = _validated_outputs(
                step,
                {output_key: workflow_artifact_ref.to_dict()},
                runner_name="artifact step",
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, workflow_artifact_ref.to_dict())
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=_contract_metrics(
                    step,
                    started=started,
                    outputs=outputs,
                    artifact_count=1,
                ),
                artifacts=[artifact_ref],
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="ArtifactStepRunner",
            )


_TOOL_CALL_STEP_TYPES = {
    StepType.TOOL_CALL,
    StepType.NOTIFICATION,
    StepType.MEMORY_INDEX,
    StepType.PERSIST,
}


def _run_parallel_branch(
    registry: FunctionStepRegistry,
    branch: Any,
    parent_buffer: StepScopedDataBufferView,
) -> dict[str, Any]:
    branch = _normalize_parallel_branch(branch, index=0)
    started_at = _utc_now_iso()
    started = time.perf_counter()
    attempts = int(branch.get("_attempts") or 1)
    branch_id = str(branch["branch_id"])
    implementation = str(branch.get("implementation") or "")
    read_keys = [str(key) for key in branch.get("read_keys", [])]
    write_keys = [str(key) for key in branch.get("write_keys", [])]
    required_output_keys = [str(key) for key in branch.get("required_output_keys", [])]

    local_values = {
        key: parent_buffer.read(key)
        for key in read_keys
        if key in parent_buffer.list_allowed_reads() and parent_buffer.exists(key)
    }
    local_buffer = DataBuffer(local_values)
    scoped = local_buffer.scope(read_keys=read_keys, write_keys=write_keys)
    raw_outputs = registry.get(implementation)(scoped) or {}
    if not isinstance(raw_outputs, dict):
        raise StepExecutionError(
            f"parallel_group branch {branch_id or implementation} returned "
            f"{type(raw_outputs).__name__}, expected dict"
        )
    missing = sorted(set(required_output_keys) - set(raw_outputs))
    if missing:
        raise StepExecutionError(
            f"parallel_group branch {branch_id or implementation} missing required outputs: "
            f"{', '.join(missing)}"
        )
    return {
        "branch_id": branch_id or implementation,
        "implementation": implementation,
        "status": StepStatus.SUCCEEDED.value,
        "outputs": raw_outputs,
        "attempts": attempts,
        "duration_ms": _elapsed_ms(started),
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "error_type": None,
        "error_message": None,
        "artifact_refs": [],
        "lineage": _parallel_branch_lineage(
            step_id=str(branch.get("_step_id") or ""),
            branch_id=branch_id,
            output_keys=sorted(str(key) for key in raw_outputs),
        ),
    }


def _branch_id(branch: dict[str, Any], *, index: int) -> str:
    raw_branch_id = branch.get("branch_id")
    raw_implementation = branch.get("implementation")
    candidate = raw_branch_id if raw_branch_id is not None else raw_implementation
    branch_id = str(candidate or "").strip()
    if not branch_id:
        raise StepExecutionError(
            f"parallel_group branch at index {index} requires branch_id or implementation"
        )
    if not _BRANCH_ID_PATTERN.fullmatch(branch_id):
        raise StepExecutionError(
            "parallel_group branch_id must contain only letters, digits, '_', '-', or '.'"
        )
    return branch_id


def _normalize_parallel_branch(
    branch: Any,
    *,
    index: int,
    step_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(branch, dict):
        raise StepExecutionError("parallel_group branch must be an object")
    implementation = str(branch.get("implementation") or "").strip()
    if not implementation:
        raise StepExecutionError("parallel_group branch implementation is required")
    normalized = dict(branch)
    normalized["implementation"] = implementation
    normalized["branch_id"] = _branch_id(normalized, index=index)
    if step_id is not None:
        normalized["_step_id"] = step_id
    return normalized


def _normalize_parallel_branches(
    branches: list[Any],
    *,
    step_id: str,
) -> list[dict[str, Any]]:
    normalized_branches = [
        _normalize_parallel_branch(branch, index=index, step_id=step_id)
        for index, branch in enumerate(branches)
    ]
    seen: dict[str, int] = {}
    for index, branch in enumerate(normalized_branches):
        branch_id = str(branch["branch_id"])
        if branch_id in seen:
            raise StepExecutionError(
                f"parallel_group branch_id must be unique: {branch_id}"
            )
        seen[branch_id] = index
    return normalized_branches


def _parallel_branch_failure_result(
    branch: dict[str, Any],
    exc: Exception,
    *,
    attempts: int | None = None,
    started_at: str | None = None,
    started: float | None = None,
) -> dict[str, Any]:
    original_error = (
        exc.original_error if isinstance(exc, _ParallelBranchExecutionError) else exc
    )
    actual_attempts = (
        exc.attempts if isinstance(exc, _ParallelBranchExecutionError) else attempts
    )
    branch_id = str(branch.get("branch_id") or "")
    return {
        "branch_id": branch_id,
        "implementation": str(branch.get("implementation") or ""),
        "status": StepStatus.FAILED.value,
        "outputs": {},
        "error_type": type(original_error).__name__,
        "error_message": str(original_error),
        "attempts": int(actual_attempts or branch.get("_attempts") or 1),
        "duration_ms": _elapsed_ms(started) if started is not None else 0.0,
        "started_at": started_at or _utc_now_iso(),
        "finished_at": _utc_now_iso(),
        "artifact_refs": [],
        "lineage": _parallel_branch_lineage(
            step_id=str(branch.get("_step_id") or ""),
            branch_id=branch_id,
            output_keys=[],
        ),
    }


def _run_parallel_branches_with_policy(
    *,
    pool: ThreadPoolExecutor,
    registry: FunctionStepRegistry,
    branches: list[dict[str, Any]],
    parent_buffer: StepScopedDataBufferView,
    failure_strategy: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    branch_results: list[dict[str, Any]] = []
    failed_branch_results: list[dict[str, Any]] = []
    pending: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    start_times: dict[Future[dict[str, Any]], float] = {}
    started_at_by_future: dict[Future[dict[str, Any]], str] = {}

    for branch in branches:
        submitted_branch = _branch_with_attempt(branch, 1)
        future = pool.submit(
            _run_parallel_branch_with_policy, registry, submitted_branch, parent_buffer
        )
        pending[future] = submitted_branch
        start_times[future] = time.perf_counter()
        started_at_by_future[future] = _utc_now_iso()

    while pending:
        timeout = _next_parallel_wait_timeout(pending, start_times)
        done, _ = wait(tuple(pending), timeout=timeout, return_when=FIRST_COMPLETED)
        if not done:
            for future in _timed_out_parallel_futures(pending, start_times):
                branch = pending.pop(future)
                future.cancel()
                failed_branch_results.append(
                    _parallel_branch_failure_result(
                        branch,
                        TimeoutError(
                            f"parallel_group branch {branch['branch_id']} exceeded timeout of "
                            f"{_branch_timeout_seconds(branch):g} seconds"
                        ),
                        attempts=int(branch.get("_attempts") or 1),
                        started_at=started_at_by_future.pop(future, None),
                        started=start_times.pop(future, None),
                    )
                )
            continue
        for future in done:
            branch = pending.pop(future)
            start_times.pop(future, None)
            started_at_by_future.pop(future, None)
            try:
                branch_result = future.result()
            except Exception as exc:
                if failure_strategy in {"fail_fast", "all_success"}:
                    raise
                failed_branch_results.append(
                    _parallel_branch_failure_result(branch, exc)
                )
                continue
            branch_results.append(branch_result)
    return branch_results, failed_branch_results


def _run_parallel_branch_with_policy(
    registry: FunctionStepRegistry,
    branch: dict[str, Any],
    parent_buffer: StepScopedDataBufferView,
) -> dict[str, Any]:
    max_retries = _branch_max_retries(branch)
    retry_on_error_types = _branch_retry_on_error_types(branch)
    no_retry_on_error_types = _branch_no_retry_on_error_types(branch)
    attempts = 0
    while True:
        attempts += 1
        attempt_branch = _branch_with_attempt(branch, attempts)
        try:
            return _run_parallel_branch(registry, attempt_branch, parent_buffer)
        except Exception as exc:
            if attempts > max_retries or not _should_retry_branch_error(
                exc,
                retry_on_error_types=retry_on_error_types,
                no_retry_on_error_types=no_retry_on_error_types,
            ):
                raise _ParallelBranchExecutionError(exc, attempts=attempts) from exc
            delay = _branch_retry_delay_seconds(branch, attempts)
            if delay > 0:
                time.sleep(delay)


def _branch_with_attempt(branch: dict[str, Any], attempts: int) -> dict[str, Any]:
    return {**branch, "_attempts": attempts}


def _branch_timeout_seconds(branch: dict[str, Any]) -> float | None:
    value = branch.get("timeout_seconds")
    if value is None:
        return None
    timeout = float(value)
    if timeout <= 0:
        raise StepExecutionError(
            "parallel_group branch timeout_seconds must be positive"
        )
    return timeout


def _branch_retry_policy(branch: dict[str, Any]) -> dict[str, Any]:
    policy = branch.get("retry_policy")
    if policy is None:
        return {}
    if not isinstance(policy, dict):
        raise StepExecutionError("parallel_group branch retry_policy must be an object")
    return dict(policy)


def _branch_max_retries(branch: dict[str, Any]) -> int:
    policy = _branch_retry_policy(branch)
    max_retries = int(policy.get("max_retries") or 0)
    if max_retries < 0:
        raise StepExecutionError(
            "parallel_group branch max_retries must be non-negative"
        )
    return max_retries


def _branch_retry_delay_seconds(branch: dict[str, Any], attempt: int) -> float:
    policy = _branch_retry_policy(branch)
    raw_delays = policy.get("retry_delay_seconds") or []
    if not isinstance(raw_delays, list):
        raise StepExecutionError(
            "parallel_group branch retry_delay_seconds must be a list"
        )
    if not raw_delays:
        return 0.0
    index = min(max(attempt - 1, 0), len(raw_delays) - 1)
    delay = float(raw_delays[index])
    if delay < 0:
        raise StepExecutionError(
            "parallel_group branch retry delay must be non-negative"
        )
    return delay


def _branch_retry_on_error_types(branch: dict[str, Any]) -> set[str]:
    policy = _branch_retry_policy(branch)
    values = policy.get("retry_on_error_types") or []
    if not isinstance(values, list):
        raise StepExecutionError(
            "parallel_group branch retry_on_error_types must be a list"
        )
    return {str(value) for value in values}


def _branch_no_retry_on_error_types(branch: dict[str, Any]) -> set[str]:
    policy = _branch_retry_policy(branch)
    values = policy.get("no_retry_on_error_types") or []
    if not isinstance(values, list):
        raise StepExecutionError(
            "parallel_group branch no_retry_on_error_types must be a list"
        )
    return {str(value) for value in values}


def _should_retry_branch_error(
    exc: Exception,
    *,
    retry_on_error_types: set[str],
    no_retry_on_error_types: set[str],
) -> bool:
    error_type = type(exc).__name__
    if error_type in no_retry_on_error_types:
        return False
    if retry_on_error_types and error_type not in retry_on_error_types:
        return False
    return True


def _next_parallel_wait_timeout(
    pending: dict[Future[dict[str, Any]], dict[str, Any]],
    start_times: dict[Future[dict[str, Any]], float],
) -> float | None:
    timeouts: list[float] = []
    now = time.perf_counter()
    for future, branch in pending.items():
        timeout = _branch_timeout_seconds(branch)
        if timeout is None:
            continue
        remaining = timeout - (now - start_times[future])
        timeouts.append(max(0.0, remaining))
    if not timeouts:
        return None
    return min(timeouts)


def _timed_out_parallel_futures(
    pending: dict[Future[dict[str, Any]], dict[str, Any]],
    start_times: dict[Future[dict[str, Any]], float],
) -> list[Future[dict[str, Any]]]:
    timed_out: list[Future[dict[str, Any]]] = []
    now = time.perf_counter()
    for future, branch in pending.items():
        timeout = _branch_timeout_seconds(branch)
        if timeout is not None and now - start_times[future] >= timeout:
            timed_out.append(future)
    return timed_out


def _parallel_group_outputs(
    step: StepSpec,
    *,
    merged_outputs: dict[str, Any],
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
    namespace_key: str,
) -> dict[str, Any]:
    outputs = dict(merged_outputs)
    if namespace_key:
        outputs[namespace_key] = {
            str(result["branch_id"]): result["outputs"] for result in branch_results
        }
    declared_write_keys = set(step.write_keys)
    result_key = str(
        step.metadata.get("branch_results_key")
        or ("branch_results" if "branch_results" in declared_write_keys else "")
    )
    failed_result_key = str(
        step.metadata.get("failed_branch_results_key")
        or (
            "failed_branch_results"
            if "failed_branch_results" in declared_write_keys
            else ""
        )
    )
    if result_key:
        result_items = (
            list(branch_results)
            if failed_result_key and failed_result_key != result_key
            else [*branch_results, *failed_branch_results]
        )
        outputs[result_key] = result_items
    if failed_result_key and failed_result_key != result_key:
        outputs[failed_result_key] = list(failed_branch_results)
    if "success_count" in declared_write_keys:
        outputs["success_count"] = len(branch_results)
    if "failure_count" in declared_write_keys:
        outputs["failure_count"] = len(failed_branch_results)
    if "partial_success" in declared_write_keys:
        outputs["partial_success"] = bool(failed_branch_results)
    summary_key = str(step.metadata.get("summary_key") or "")
    if summary_key:
        outputs[summary_key] = {
            "branch_count": len(branch_results) + len(failed_branch_results),
            "succeeded_branch_count": len(branch_results),
            "failed_branch_count": len(failed_branch_results),
            "success_count": len(branch_results),
            "failure_count": len(failed_branch_results),
            "partial_success": bool(failed_branch_results),
            "succeeded_branch_ids": sorted(
                str(result.get("branch_id") or "") for result in branch_results
            ),
            "failed_branch_ids": sorted(
                str(result.get("branch_id") or "") for result in failed_branch_results
            ),
        }
    return outputs


def _subworkflow_request(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> dict[str, Any]:
    input_map = step.metadata.get("input_map")
    if isinstance(input_map, dict):
        request = {}
        for target_key, source_key in input_map.items():
            request[str(target_key)] = buffer.read(str(source_key))
        return request

    request = step.metadata.get("request")
    request_key = step.metadata.get("request_key")
    if request_key is not None:
        request = buffer.read(str(request_key))
    if request is None:
        request = {}
    if not isinstance(request, dict):
        raise StepExecutionError(
            f"subworkflow step {step.step_id} request must be an object"
        )
    return dict(request)


def _subworkflow_mapped_outputs(
    step: StepSpec, child_output: dict[str, Any]
) -> dict[str, Any]:
    output_map = step.metadata.get("output_map")
    if not isinstance(output_map, dict):
        return {}
    outputs = {}
    for parent_key, child_key in output_map.items():
        key = str(child_key)
        if key in child_output:
            outputs[str(parent_key)] = child_output[key]
    return outputs


def _subworkflow_optional_outputs(
    *,
    step: StepSpec,
    child_run_record: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    declared = set(step.write_keys)
    if "child_runs" in declared:
        outputs["child_runs"] = [child_run_record]
    if "subworkflow_event_summary" in declared:
        outputs["subworkflow_event_summary"] = _subworkflow_event_summary(result)
    if "subworkflow_cancellation_policy" in declared:
        outputs["subworkflow_cancellation_policy"] = _subworkflow_cancellation_policy(
            step
        )
    return outputs


def _record_child_manifest_parent_link(
    *,
    artifact_manager: ArtifactManager,
    child_run_id: str,
    parent_run_id: str,
    parent_step_id: str,
) -> None:
    manifest_path = artifact_manager.run_dir(child_run_id) / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    manifest["parent_run_id"] = parent_run_id
    manifest["parent_step_id"] = parent_step_id
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _subworkflow_child_run_record(
    *,
    step: StepSpec,
    child_run_id: str,
    workflow: Any,
    result: Any,
) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "child_run_id": child_run_id,
        "workflow_id": workflow.workflow_id,
        "workflow_version": workflow.version,
        "status": result.status.value,
        "manifest_path": result.manifest_path,
    }


def _subworkflow_event_summary(result: Any) -> dict[str, Any]:
    manifest = dict(result.manifest) if isinstance(result.manifest, dict) else {}
    raw_metrics = manifest.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    failed_step_id = result.error.step_id if result.error else None
    return {
        "event_count": int(
            metrics.get("event_count") or manifest.get("event_count") or 0
        ),
        "failed_step_id": failed_step_id,
        "status": result.status.value,
        "path": list(result.path),
    }


def _subworkflow_failure_propagation(step: StepSpec) -> str:
    return str(step.metadata.get("failure_propagation") or "fail_parent")


def _subworkflow_inherits_budget(step: StepSpec) -> bool:
    return bool(step.metadata.get("inherit_budget", False))


def _subworkflow_budget_scope(step: StepSpec) -> str:
    return str(
        step.metadata.get("budget_scope")
        or ("shared" if _subworkflow_inherits_budget(step) else "isolated")
    )


def _subworkflow_cancellation_policy(step: StepSpec) -> dict[str, Any]:
    raw_policy = step.metadata.get("cancellation_policy")
    if isinstance(raw_policy, dict):
        policy = dict(raw_policy)
    else:
        policy = {}
    policy.setdefault("cascade", bool(step.metadata.get("cascade_cancel", True)))
    return policy


def _subworkflow_failure_outcome(
    *,
    step: StepSpec,
    workflow_id: str,
    result: Any,
    outputs: dict[str, Any],
    metrics: dict[str, Any],
    lineage: list[dict[str, Any]],
) -> StepOutcome:
    policy = _subworkflow_failure_propagation(step)
    error_type = result.error.error_type if result.error else "SubworkflowFailed"
    error_message = (
        result.error.message if result.error else f"subworkflow failed: {workflow_id}"
    )
    error_details = {
        "child_run_id": metrics.get("child_run_id"),
        "child_status": result.status.value,
        "failure_propagation": policy,
    }
    if policy == "block_parent":
        return StepOutcome(
            status=StepStatus.BLOCKED,
            outputs=outputs,
            error_type=error_type,
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
        )
    if policy == "best_effort":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            error_type="SubworkflowPartialFailure",
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
            next_hint="best_effort",
        )
    if policy == "fallback_output":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            error_type="SubworkflowFallbackUsed",
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
            next_hint="fallback_output",
        )
    if policy == "isolate_failure":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            error_type="SubworkflowFailureIsolated",
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
            next_hint="isolate_failure",
        )
    return StepOutcome(
        status=StepStatus.FAILED,
        outputs=outputs,
        error_type=error_type,
        error_message=error_message,
        error_details=error_details,
        metrics=metrics,
        lineage=lineage,
    )


def _subworkflow_failure_policy_outputs(
    *,
    step: StepSpec,
    result: Any,
) -> dict[str, Any]:
    policy = _subworkflow_failure_propagation(step)
    error_type = result.error.error_type if result.error else "SubworkflowFailed"
    error_message = result.error.message if result.error else "subworkflow failed"
    outputs: dict[str, Any] = {}
    if policy == "best_effort":
        outputs["partial_success"] = True
        outputs["child_failure"] = {
            "error_type": error_type,
            "error_message": error_message,
            "status": result.status.value,
        }
    elif policy == "fallback_output":
        fallback_output = step.metadata.get("fallback_output")
        if isinstance(fallback_output, dict):
            outputs.update(fallback_output)
    elif policy == "isolate_failure":
        outputs["child_failure"] = {
            "error_type": error_type,
            "error_message": error_message,
            "status": result.status.value,
        }
    return outputs


def _merge_parallel_outputs(
    merged: dict[str, Any],
    outputs: dict[str, Any],
    *,
    conflict_strategy: str,
    step_id: str,
) -> None:
    for key, value in outputs.items():
        if key not in merged:
            merged[key] = value
            continue
        if conflict_strategy == "error":
            raise StepExecutionError(
                f"parallel_group step {step_id} output conflict for key {key}"
            )
        if conflict_strategy == "first_wins":
            continue
        if conflict_strategy == "last_wins":
            merged[key] = value
            continue
        if conflict_strategy == "last_write":
            merged[key] = value
            continue
        if conflict_strategy == "merge_list":
            existing = merged[key] if isinstance(merged[key], list) else [merged[key]]
            addition = value if isinstance(value, list) else [value]
            merged[key] = [*existing, *addition]
            continue
        if conflict_strategy == "merge_dict":
            if not isinstance(merged[key], dict) or not isinstance(value, dict):
                raise StepExecutionError(
                    f"parallel_group step {step_id} cannot merge non-dict output for {key}"
                )
            merged[key] = {**merged[key], **value}
            continue
        raise StepExecutionError(
            f"unsupported parallel conflict strategy: {conflict_strategy}"
        )


def _enforce_parallel_failure_strategy(
    *,
    failure_strategy: str,
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
    min_success: int,
) -> None:
    failure_count = len(failed_branch_results)
    success_count = len(branch_results)
    if failure_strategy in {"fail_fast", "all_success"} and failure_count:
        raise StepExecutionError(f"{failure_count} parallel branch(es) failed")
    if failure_strategy == "min_success" and success_count < max(1, min_success):
        raise StepExecutionError(
            f"parallel_group requires at least {max(1, min_success)} successful branch(es); "
            f"got {success_count}"
        )


def _publish_parallel_branch_artifacts(
    *,
    artifact_manager: ArtifactManager | None,
    run_id: str | None,
    step: StepSpec,
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
) -> list[StorageArtifactRef]:
    if artifact_manager is None or run_id is None:
        return []
    if not _parallel_branch_artifacts_enabled(step):
        return []

    artifact_refs: list[StorageArtifactRef] = []
    for branch_result in [*branch_results, *failed_branch_results]:
        branch_id = str(branch_result.get("branch_id") or "")
        payload = {
            "branch_result": branch_result,
            "outputs": branch_result.get("outputs") or {},
            "metrics": {
                "attempts": branch_result.get("attempts"),
                "duration_ms": branch_result.get("duration_ms"),
                "started_at": branch_result.get("started_at"),
                "finished_at": branch_result.get("finished_at"),
            },
            "error": {
                "error_type": branch_result.get("error_type"),
                "error_message": branch_result.get("error_message"),
            },
        }
        relative_path = f"parallel/{step.step_id}/{branch_id}.json"
        path = artifact_manager.write_json(run_id, relative_path, payload)
        data = path.read_bytes()
        artifact_ref = StorageArtifactRef(
            artifact_id=f"parallel:{step.step_id}:{branch_id}",
            run_id=run_id,
            step_id=step.step_id,
            artifact_type="parallel_branch",
            path=relative_path,
            content_type="application/json",
            size_bytes=len(data),
            checksum=sha256(data).hexdigest(),
            redacted=True,
            metadata={
                "branch_id": branch_id,
                "implementation": branch_result.get("implementation"),
                "status": branch_result.get("status"),
                "manifest_key": f"parallel:{step.step_id}:{branch_id}",
            },
        )
        artifact_payload = artifact_ref.to_dict()
        branch_result.setdefault("artifact_refs", []).append(artifact_payload)
        artifact_refs.append(artifact_ref)
    return artifact_refs


def _parallel_branch_artifacts_enabled(step: StepSpec) -> bool:
    metadata = dict(step.metadata or {})
    if bool(metadata.get("write_branch_artifacts")):
        return True
    policy = step.artifact_policy
    if policy is None:
        return False
    return bool(
        policy.write_step_output or "parallel_branch" in set(policy.artifact_types)
    )


def _parallel_group_lineage(
    step: StepSpec,
    branch_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    for branch_result in branch_results:
        branch_id = str(branch_result.get("branch_id") or "")
        output_keys = sorted(str(key) for key in (branch_result.get("outputs") or {}))
        lineage.append(
            {
                "step_id": step.step_id,
                "branch_id": branch_id,
                "output_keys": output_keys,
            }
        )
    return lineage


def _parallel_branch_lineage(
    *,
    step_id: str,
    branch_id: str,
    output_keys: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "step_id": step_id,
            "branch_id": branch_id,
            "output_keys": list(output_keys),
        }
    ]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_metadata_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _elapsed_ms(started: float | None) -> float:
    if started is None:
        return 0.0
    return round((time.perf_counter() - started) * 1000, 3)


def _single_tool_call_from_step(
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
    return _tool_call_from_payload(step, buffer, raw_call)


def _tool_call_metrics(observation: Any) -> dict[str, Any]:
    return {
        "tool_name": observation.call.tool_name,
        "tool_call_id": observation.call.call_id,
        "tool_status": observation.status.value,
        "elapsed_ms": observation.elapsed_ms,
        "output_bytes": observation.result.output_bytes,
        "artifact_ref_count": len(observation.result.artifact_refs),
        "approval_required": observation.status.value == "approval_required",
    }


def _tool_batch_metrics(observations: list[Any], *, max_workers: int) -> dict[str, Any]:
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


def _parallel_group_metrics(
    *,
    branches: list[Any],
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
    conflict_strategy: str,
    failure_strategy: str,
    min_success: int,
    max_workers: int,
    output_keys: list[str],
) -> dict[str, Any]:
    success_count = len(branch_results)
    failure_count = len(failed_branch_results)
    return {
        "branch_count": len(branches),
        "succeeded_branch_count": success_count,
        "failed_branch_count": failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "partial_success": failure_count > 0,
        "conflict_strategy": conflict_strategy,
        "failure_strategy": failure_strategy,
        "min_success": max(1, min_success),
        "max_workers": min(max_workers, len(branches)),
        "branch_ids": sorted(
            str(result.get("branch_id") or "") for result in branch_results
        ),
        "failed_branch_ids": sorted(
            str(result.get("branch_id") or "") for result in failed_branch_results
        ),
        "output_keys": sorted(output_keys),
        "output_key_count": len(output_keys),
    }


def _subworkflow_metrics(
    *,
    child_run_id: str,
    workflow_id: str,
    workflow_version: str,
    result: Any,
) -> dict[str, Any]:
    manifest = result.manifest or {}
    workflow_metrics = manifest.get("metrics") or {}
    return {
        "child_run_id": child_run_id,
        "child_workflow_id": workflow_id,
        "child_workflow_version": workflow_version,
        "child_status": result.status.value,
        "child_step_count": int(manifest.get("step_count") or len(result.step_results)),
        "child_artifact_count": int(
            workflow_metrics.get("artifact_count")
            or len(manifest.get("artifacts") or {})
        ),
        "child_event_count": int(
            workflow_metrics.get("event_count") or manifest.get("event_count") or 0
        ),
        "child_manifest_path": result.manifest_path,
        "child_events_path": result.events_path,
    }


def _observation_key(step: StepSpec) -> str:
    return str(
        step.metadata.get("observation_key") or f"{step.step_id}_tool_observation"
    )


def _result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or f"{step.step_id}_tool_result")


def _metadata_float(step: StepSpec, key: str, default: float | None) -> float | None:
    value = step.metadata.get(key, default)
    if value is None:
        return None
    return float(value)


def _buffer_metric(
    buffer: StepScopedDataBufferView,
    step: StepSpec,
    metadata_key: str,
    default_key: str,
) -> float | None:
    value = _buffer_value(buffer, step.metadata.get(f"{metadata_key}_key"), None)
    if value is None:
        value = _buffer_value(buffer, default_key, None)
    if value is None:
        return None
    return float(value)


def _buffer_value(buffer: StepScopedDataBufferView, key: Any, default: Any) -> Any:
    if key is None:
        return default
    key = str(key)
    if key not in buffer.list_allowed_reads() or not buffer.exists(key):
        return default
    return buffer.read(key)


def _memory_query_from_step(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> MemoryQuery:
    raw_query = step.metadata.get("query")
    if raw_query is None and step.metadata.get("query_key") is not None:
        raw_query = buffer.read(str(step.metadata["query_key"]))
    if raw_query is None:
        raise StepExecutionError(f"memory_recall step {step.step_id} requires a query")

    if isinstance(raw_query, dict):
        payload: dict[str, Any] = dict(raw_query)
    else:
        payload = {"query": str(raw_query)}

    for key in (
        "scopes",
        "kinds",
        "filters",
        "limit",
        "min_score",
        "max_context_tokens",
    ):
        if key in step.metadata:
            payload[key] = step.metadata[key]

    if step.metadata.get("filters_key") is not None:
        raw_filters = buffer.read(str(step.metadata["filters_key"]))
        if not isinstance(raw_filters, dict):
            raise StepExecutionError(
                f"memory_recall step {step.step_id} filters_key must reference an object"
            )
        existing_filters = payload.get("filters")
        payload["filters"] = {
            **dict(raw_filters),
            **(dict(existing_filters) if isinstance(existing_filters, dict) else {}),
        }

    return MemoryQuery.from_dict(payload)


def _memory_records_from_step(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> list[Any]:
    raw_records = step.metadata.get("records")
    if raw_records is None and step.metadata.get("records_key") is not None:
        raw_records = buffer.read(str(step.metadata["records_key"]))
    if raw_records is None:
        raise StepExecutionError(f"memory_write step {step.step_id} requires records")
    if isinstance(raw_records, dict):
        nested_records = raw_records.get("records")
        if isinstance(nested_records, list):
            return list(nested_records)
        return [dict(raw_records)]
    if isinstance(raw_records, (list, tuple)):
        return list(raw_records)
    raise StepExecutionError(
        f"memory_write step {step.step_id} records must be an object or list of objects"
    )


def _memory_actor_from_step(step: StepSpec, buffer: StepScopedDataBufferView) -> str:
    if step.metadata.get("actor_key") is not None:
        actor = buffer.read(str(step.metadata["actor_key"]))
    else:
        actor = (
            step.metadata.get("actor")
            or step.metadata.get("requested_by")
            or step.step_id
        )
    return str(actor or step.step_id)


def _memory_consolidation_request_from_step(
    step: StepSpec,
    buffer: StepScopedDataBufferView,
    *,
    run_id: str | None,
) -> MemoryConsolidationRequest:
    raw_memory_ids = step.metadata.get("memory_ids")
    if raw_memory_ids is None and step.metadata.get("memory_ids_key") is not None:
        raw_memory_ids = buffer.read(str(step.metadata["memory_ids_key"]))
    raw_query = step.metadata.get("query")
    if raw_query is None and step.metadata.get("query_key") is not None:
        raw_query = buffer.read(str(step.metadata["query_key"]))
    raw_filters = step.metadata.get("filters")
    if raw_filters is None and step.metadata.get("filters_key") is not None:
        raw_filters = buffer.read(str(step.metadata["filters_key"]))

    memory_ids = _coerce_memory_ids_for_consolidation(raw_memory_ids, step=step)
    query = _coerce_query_for_consolidation(raw_query, step=step)
    filters = _coerce_filters_for_consolidation(raw_filters, step=step)
    payload: dict[str, Any] = {
        "memory_ids": memory_ids,
        "filters": filters,
        "actor": _memory_actor_from_step(step, buffer),
        "run_id": run_id or step.metadata.get("run_id"),
        "reason": step.metadata.get("reason"),
    }
    if query is not None:
        payload["query"] = query.to_dict()
    return MemoryConsolidationRequest.from_dict(payload)


def _coerce_memory_ids_for_consolidation(value: Any, *, step: StepSpec) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    raise StepExecutionError(
        f"memory_consolidate step {step.step_id} memory_ids must be a string or list"
    )


def _coerce_query_for_consolidation(
    value: Any, *, step: StepSpec
) -> MemoryQuery | None:
    if value is None:
        return None
    if isinstance(value, MemoryQuery):
        return value
    if isinstance(value, dict):
        return MemoryQuery.from_dict(dict(value))
    return MemoryQuery(query=str(value))


def _coerce_filters_for_consolidation(value: Any, *, step: StepSpec) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StepExecutionError(
            f"memory_consolidate step {step.step_id} filters must be an object"
        )
    return dict(value)


def _memory_recall_result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or "memory_recall_result")


def _memory_context_key(step: StepSpec) -> str:
    return str(step.metadata.get("context_key") or "memory_context")


def _memory_records_key(step: StepSpec) -> str:
    return str(
        step.metadata.get("records_key")
        or step.metadata.get("records_output_key")
        or "memory_records"
    )


def _memory_write_result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or "memory_write_result")


def _memory_consolidate_result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or "memory_consolidate_result")


def _join_summary(step: StepSpec, inputs: dict[str, Any]) -> dict[str, Any]:
    strategy = str(
        step.metadata.get("join_policy")
        or step.metadata.get("strategy")
        or step.metadata.get("wait_strategy")
        or "all_success"
    )
    branch_results_key = str(step.metadata.get("branch_results_key") or "")
    branch_results = inputs.get(branch_results_key) if branch_results_key else None
    if not isinstance(branch_results, list):
        branch_results = []
    succeeded_branches = [
        result
        for result in branch_results
        if isinstance(result, dict)
        and result.get("status") == StepStatus.SUCCEEDED.value
    ]
    failed_branches = [
        result
        for result in branch_results
        if isinstance(result, dict)
        and result.get("status") != StepStatus.SUCCEEDED.value
    ]
    required_upstreams = _join_required_upstream_step_ids(step)
    optional_upstreams = _join_optional_upstream_step_ids(step)
    upstream_statuses = _join_upstream_statuses(step, inputs, branch_results)
    succeeded_upstreams = _join_upstreams_by_status(
        upstream_statuses, {StepStatus.SUCCEEDED.value}
    )
    failed_upstreams = _join_upstreams_by_status(
        upstream_statuses,
        {StepStatus.FAILED.value, StepStatus.BLOCKED.value, StepStatus.TIMEOUT.value},
    )
    skipped_upstreams = _join_upstreams_by_status(
        upstream_statuses, {StepStatus.SKIPPED.value}
    )
    missing_upstreams = sorted(
        step_id for step_id in required_upstreams if step_id not in upstream_statuses
    )
    pending_upstreams = sorted(
        step_id
        for step_id in required_upstreams
        if upstream_statuses.get(step_id)
        in {StepStatus.PENDING.value, StepStatus.READY.value, StepStatus.RUNNING.value}
    )
    quorum = int(
        step.metadata.get("quorum")
        or step.metadata.get("join_quorum")
        or len(branch_results)
        or 0
    )
    timed_out = _join_timeout_exceeded(step, inputs)
    on_timeout = str(step.metadata.get("on_timeout") or "fail")

    if not required_upstreams:
        if strategy == "all_success":
            ready = not failed_branches and len(succeeded_branches) == len(
                branch_results
            )
        elif strategy == "any_success":
            ready = bool(succeeded_branches)
        elif strategy == "quorum":
            ready = len(succeeded_branches) >= quorum
        elif strategy == "best_effort":
            ready = bool(branch_results) or bool(inputs)
        elif strategy == "timeout_join":
            ready = (
                bool(inputs)
                if not timed_out
                else on_timeout in {"best_effort", "partial"}
            )
        else:
            raise StepExecutionError(f"unsupported join strategy: {strategy}")
    elif strategy == "all_success":
        ready = not missing_upstreams and not pending_upstreams and not failed_upstreams
    elif strategy == "any_success":
        ready = bool(succeeded_upstreams) and not pending_upstreams
    elif strategy == "quorum":
        ready = len(succeeded_upstreams) >= quorum and not pending_upstreams
    elif strategy == "best_effort":
        ready = not missing_upstreams and not pending_upstreams
    elif strategy == "timeout_join":
        ready = (not missing_upstreams and not pending_upstreams) or (
            timed_out and on_timeout in {"best_effort", "partial"}
        )
    else:
        raise StepExecutionError(f"unsupported join strategy: {strategy}")
    if strategy == "timeout_join" and timed_out and on_timeout == "fail":
        ready = False
    decision = _join_decision(
        ready=ready,
        strategy=strategy,
        timed_out=timed_out,
        on_timeout=on_timeout,
        failed_upstreams=failed_upstreams,
        missing_upstreams=missing_upstreams,
        pending_upstreams=pending_upstreams,
    )
    return {
        "strategy": strategy,
        "join_policy": strategy,
        "ready": ready,
        "decision": decision,
        "joined_keys": sorted(inputs),
        "inputs": inputs,
        "branch_count": len(branch_results),
        "succeeded_branch_count": len(succeeded_branches),
        "failed_branch_count": len(failed_branches),
        "quorum": quorum if strategy == "quorum" else None,
        "required_upstream_step_ids": required_upstreams,
        "optional_upstream_step_ids": optional_upstreams,
        "succeeded_upstreams": succeeded_upstreams,
        "failed_upstreams": failed_upstreams,
        "missing_upstreams": missing_upstreams,
        "skipped_upstreams": skipped_upstreams,
        "pending_upstreams": pending_upstreams,
        "timed_out": timed_out,
        "on_timeout": on_timeout if strategy == "timeout_join" else None,
    }


def _join_required_upstream_step_ids(step: StepSpec) -> list[str]:
    raw = (
        step.metadata.get("required_upstream_step_ids")
        or step.metadata.get("upstream_step_ids")
        or []
    )
    if not isinstance(raw, list):
        raise StepExecutionError("join required_upstream_step_ids must be a list")
    return [str(item) for item in raw]


def _join_optional_upstream_step_ids(step: StepSpec) -> list[str]:
    raw = step.metadata.get("optional_upstream_step_ids") or []
    if not isinstance(raw, list):
        raise StepExecutionError("join optional_upstream_step_ids must be a list")
    return [str(item) for item in raw]


def _join_upstream_statuses(
    step: StepSpec,
    inputs: dict[str, Any],
    branch_results: list[dict[str, Any]],
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    raw_statuses = inputs.get(
        str(step.metadata.get("upstream_statuses_key") or "upstream_statuses")
    )
    if isinstance(raw_statuses, dict):
        statuses.update({str(key): str(value) for key, value in raw_statuses.items()})
    for step_id in [
        *_join_required_upstream_step_ids(step),
        *_join_optional_upstream_step_ids(step),
    ]:
        key = f"{step_id}_status"
        if key in inputs:
            statuses[step_id] = str(inputs[key])
    for result in branch_results:
        if not isinstance(result, dict):
            continue
        branch_id = result.get("branch_id")
        status = result.get("status")
        if branch_id is not None and status is not None:
            statuses[str(branch_id)] = str(status)
    return statuses


def _join_upstreams_by_status(
    upstream_statuses: dict[str, str],
    statuses: set[str],
) -> list[str]:
    return sorted(
        step_id for step_id, status in upstream_statuses.items() if status in statuses
    )


def _join_timeout_exceeded(step: StepSpec, inputs: dict[str, Any]) -> bool:
    if (
        str(step.metadata.get("join_policy") or step.metadata.get("strategy") or "")
        != "timeout_join"
    ):
        return False
    timeout_seconds = step.metadata.get("timeout_seconds")
    if timeout_seconds is None:
        return False
    started_at = inputs.get(
        "join_wait_started_at", step.metadata.get("join_wait_started_at")
    )
    if started_at is None:
        return False
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise StepExecutionError(f"invalid join_wait_started_at: {started_at}") from exc
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
    return elapsed >= float(timeout_seconds)


def _join_decision(
    *,
    ready: bool,
    strategy: str,
    timed_out: bool,
    on_timeout: str,
    failed_upstreams: list[str],
    missing_upstreams: list[str],
    pending_upstreams: list[str],
) -> str:
    if strategy == "timeout_join" and timed_out:
        if on_timeout in {"best_effort", "partial"} and ready:
            return "partial_join"
        return "timeout"
    if ready:
        return "joined"
    if failed_upstreams:
        return "failed_upstream"
    if missing_upstreams or pending_upstreams:
        return "waiting"
    return "not_ready"


def _human_next_hint(decision: Any) -> str | None:
    if isinstance(decision, dict):
        value = decision.get("decision") or decision.get("status")
    else:
        value = decision
    if value is None:
        return None
    value = str(value)
    if value in {"approved", "rejected", "needs_changes"}:
        return f"human_{value}"
    return value


def _tool_calls_from_step(
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
    return [_tool_call_from_payload(step, buffer, payload) for payload in raw_calls]


def _tool_call_from_payload(
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


def _tool_policy_from_step(step: StepSpec) -> ToolPolicy:
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
    )


def _agent_loop_error_details(result_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = result_payload.get("diagnostics")
    if isinstance(diagnostics, dict):
        details = {
            "agent_loop_status": result_payload.get("status"),
            "stop_reason": diagnostics.get("stop_reason"),
            "severity": diagnostics.get("severity"),
            "healthy": diagnostics.get("healthy"),
            "summary": diagnostics.get("summary"),
            "issues": diagnostics.get("issues") or [],
            "suggestions": diagnostics.get("suggestions") or [],
        }
        if diagnostics.get("stop_reason") == "global_budget_exceeded":
            details["budget_exceeded"] = True
            metrics = result_payload.get("metrics")
            if isinstance(metrics, dict):
                details["global_budget_check"] = metrics.get("global_budget_check")
                details["global_budget_usage"] = metrics.get("global_budget_usage")
        return details
    return {"agent_loop_status": result_payload.get("status")}


def _agent_loop_metrics_payload(result: Any) -> dict[str, Any]:
    metrics = result.metrics.to_dict()
    trajectory = [dict(item) for item in getattr(result, "trajectory", [])]
    metrics["trajectory_summary"] = {
        "iteration_count": len(trajectory),
        "tool_call_count": len(getattr(result, "tool_calls", []) or []),
        "memory_op_count": len(getattr(result, "memory_ops", []) or []),
        "termination_reason": getattr(result, "termination_reason", None),
        "max_steps_reached": bool(getattr(result, "max_steps_reached", False)),
        "trace_id": getattr(result, "trace_id", None),
    }
    return metrics


def _agent_loop_trace_events(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "event_type": "agent_loop_trajectory",
            "trace_id": getattr(result, "trace_id", None),
            "trace_ref": getattr(result, "trace_ref", None),
            "termination_reason": getattr(result, "termination_reason", None),
            "max_steps_reached": bool(getattr(result, "max_steps_reached", False)),
            "trajectory": [dict(item) for item in getattr(result, "trajectory", [])],
        }
    ]


def _validated_outputs(
    step: StepSpec,
    raw_outputs: dict[str, Any] | None,
    *,
    runner_name: str,
    allow_extra: bool = False,
    allow_missing_required: bool = False,
) -> dict[str, Any]:
    outputs = raw_outputs or {}
    if not isinstance(outputs, dict):
        raise StepExecutionError(
            f"{runner_name} {step.step_id} returned {type(outputs).__name__}, expected dict"
        )
    extra_keys = sorted(set(outputs) - set(step.write_keys))
    if extra_keys and not allow_extra:
        raise StepExecutionError(
            f"{runner_name} {step.step_id} returned undeclared output keys: "
            f"{', '.join(extra_keys)}"
        )
    missing = sorted(set(step.required_output_keys) - set(outputs))
    if missing and not allow_missing_required:
        raise StepExecutionError(
            f"{runner_name} {step.step_id} did not return required output keys: "
            f"{', '.join(missing)}"
        )
    return {
        str(key): value
        for key, value in outputs.items()
        if str(key) in set(step.write_keys)
    }


def _json_artifact_bytes(content: Any) -> bytes:
    from framework.shared.json import to_jsonable as to_json_safe

    return (
        json.dumps(
            to_json_safe(content),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _contract_metrics(
    step: StepSpec,
    *,
    started: float,
    outputs: dict[str, Any] | None = None,
    artifact_count: int = 0,
) -> dict[str, Any]:
    actual_outputs = outputs or {}
    return {
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "attempt": 1,
        "input_key_count": len(step.read_keys),
        "output_key_count": len(actual_outputs),
        "artifact_count": artifact_count,
    }


def _with_contract_metrics(
    metrics: dict[str, Any],
    step: StepSpec,
    *,
    started: float,
    outputs: dict[str, Any] | None = None,
    artifact_count: int = 0,
) -> dict[str, Any]:
    return {
        **metrics,
        **_contract_metrics(
            step,
            started=started,
            outputs=outputs,
            artifact_count=artifact_count,
        ),
    }


def _failed_outcome(
    step: StepSpec,
    exc: Exception,
    *,
    started: float,
    runner_name: str,
) -> StepOutcome:
    return StepOutcome(
        status=StepStatus.FAILED,
        error_type=type(exc).__name__,
        error_message=str(exc),
        error_details={"runner": runner_name},
        metrics=_contract_metrics(step, started=started),
    )


def _observations_key(step: StepSpec) -> str:
    return str(step.metadata.get("observations_key") or "tool_observations")


def _results_key(step: StepSpec) -> str:
    return str(step.metadata.get("results_key") or "tool_results")
