from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from typing import Any, Protocol

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepStatus, StepType
from core.framework.workflow.buffer import DataBuffer, ScopedDataBuffer
from core.framework.workflow.result import StepOutcome
from storage.artifacts import ArtifactRef

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


def build_default_step_runner_registry(
    function_registry: FunctionStepRegistry | None = None,
    *,
    tool_registry: Any | None = None,
    agent_runner: Any | None = None,
    agent_registry: dict[str, Any] | None = None,
    workflow_registry: dict[str, Any] | None = None,
    artifact_manager: ArtifactManager | None = None,
    run_id: str | None = None,
    approval_store: Any | None = None,
    secret_provider: Any | None = None,
    global_budget_tracker: Any | None = None,
    max_parallel_workers: int = 4,
    max_tool_batch_workers: int = 4,
) -> StepRunnerRegistry:
    """Build the standard runtime registry from explicitly injected dependencies."""

    registry = StepRunnerRegistry()

    if function_registry is not None:
        registry.register(StepType.FUNCTION, FunctionStepRunner(function_registry))
        registry.register(
            StepType.PARALLEL_GROUP,
            ParallelGroupStepRunner(function_registry, max_workers=max_parallel_workers),
        )

    if tool_registry is not None:
        tool_call_runner = ToolCallStepRunner(
            tool_registry,
            artifact_manager=artifact_manager,
            run_id=run_id,
            approval_store=approval_store,
            secret_provider=secret_provider,
        )
        for step_type in _TOOL_CALL_STEP_TYPES:
            registry.register(step_type, tool_call_runner)
        registry.register(
            StepType.TOOL_BATCH,
            ToolBatchStepRunner(
                tool_registry,
                artifact_manager=artifact_manager,
                run_id=run_id,
                secret_provider=secret_provider,
                max_workers=max_tool_batch_workers,
            ),
        )

    if agent_runner is not None and agent_registry:
        registry.register(
            StepType.AGENT_LOOP,
            AgentLoopStepRunner(
                agent_runner,
                agent_registry,
                global_budget_tracker=global_budget_tracker,
            ),
        )

    registry.register(StepType.ROUTER, RouterStepRunner())
    registry.register(StepType.JOIN, JoinStepRunner())
    registry.register(StepType.QUALITY_GATE, QualityGateStepRunner())
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    registry.register(StepType.ARTIFACT, ArtifactStepRunner(artifact_manager, run_id=run_id))

    if workflow_registry is not None:
        registry.register(
            StepType.SUBWORKFLOW,
            SubworkflowStepRunner(
                workflow_registry,
                registry,
                artifact_manager=artifact_manager,
                run_id=run_id,
            ),
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
            raise StepExecutionError(f"function step is not registered: {implementation}") from exc

    def is_registered(self, implementation: str) -> bool:
        return implementation in self._functions


class FunctionStepRunner:
    def __init__(self, registry: FunctionStepRegistry) -> None:
        self._registry = registry

    def can_resolve(self, step: StepSpec) -> bool:
        return self._registry.is_registered(step.implementation)

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

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.TOOL_BATCH:
            raise StepExecutionError(f"unsupported step type for ToolBatchStepRunner: {step.step_type}")

        tool_calls = _tool_calls_from_step(step, buffer)
        policy = _tool_policy_from_step(step)
        from core.framework.tools import ToolBatchExecutor

        executor = ToolBatchExecutor(
            self._registry,
            artifact_manager=self._artifact_manager,
            run_id=self._run_id,
            secret_provider=self._secret_provider,
            max_workers=self._max_workers,
        )
        observations = executor.execute_batch(tool_calls, policy)
        observation_payloads = [observation.to_dict() for observation in observations]
        result_payloads = [observation.result.to_dict() for observation in observations]
        metrics = _tool_batch_metrics(observations, max_workers=self._max_workers)
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
                metrics=metrics,
            )
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs, metrics=metrics)


class AgentLoopStepRunner:
    def __init__(
        self,
        agent_runner: Any,
        agent_registry: dict[str, Any],
        global_budget_tracker: Any | None = None,
    ) -> None:
        self._agent_runner = agent_runner
        self._agent_registry = dict(agent_registry)
        self._global_budget_tracker = global_budget_tracker

    def can_resolve(self, step: StepSpec) -> bool:
        agent_id = str(step.metadata.get("agent_id") or step.implementation)
        return agent_id in self._agent_registry

    def configure_global_budget_tracker(self, global_budget_tracker: Any | None) -> None:
        self._global_budget_tracker = global_budget_tracker

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.AGENT_LOOP:
            raise StepExecutionError(f"unsupported step type for AgentLoopStepRunner: {step.step_type}")

        agent_id = str(step.metadata.get("agent_id") or step.implementation)
        try:
            agent = self._agent_registry[agent_id]
        except KeyError as exc:
            raise StepExecutionError(f"agent is not registered: {agent_id}") from exc

        inputs = {
            key: buffer.read(key)
            for key in step.read_keys
            if buffer.exists(key)
        }
        conversation_id = step.metadata.get("conversation_id")
        if "conversation_id_key" in step.metadata:
            conversation_id = buffer.read(str(step.metadata["conversation_id_key"]))

        run_kwargs: dict[str, Any] = {
            "conversation_id": str(conversation_id) if conversation_id else None,
        }
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
        diagnostics_key = str(step.metadata.get("diagnostics_key") or "agent_loop_diagnostics")
        trace_key = str(step.metadata.get("trace_key") or "agent_loop_trace")
        outputs[result_key] = result_payload
        outputs[events_key] = result.events
        outputs[metrics_key] = result.metrics.to_dict()
        outputs[diagnostics_key] = (
            result.diagnostics.to_dict() if result.diagnostics is not None else None
        )
        outputs[trace_key] = result.trace

        for key, value in outputs.items():
            if key in buffer.list_allowed_writes():
                buffer.write(key, value, lineage={"step_id": step.step_id, "agent_id": agent_id})

        status_value = str(result.status.value)
        if result.success:
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=result.metrics.to_dict(),
            )
        if status_value == "waiting_for_approval":
            return StepOutcome(
                status=StepStatus.PAUSED,
                outputs=outputs,
                error_type="AgentLoopWaitingForApproval",
                error_message=result.error or f"agent loop waiting for approval: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=result.metrics.to_dict(),
            )
        if status_value == "stalled":
            return StepOutcome(
                status=StepStatus.BLOCKED,
                outputs=outputs,
                error_type="AgentLoopStalled",
                error_message=result.error or f"agent loop stalled: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=result.metrics.to_dict(),
            )
        if status_value == "blocked":
            return StepOutcome(
                status=StepStatus.BLOCKED,
                outputs=outputs,
                error_type="AgentLoopBlocked",
                error_message=result.error or f"agent loop blocked: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=result.metrics.to_dict(),
            )
        return StepOutcome(
            status=StepStatus.FAILED,
            outputs=outputs,
            error_type="AgentLoopFailed",
            error_message=result.error or f"agent loop failed: {agent_id}",
            error_details=_agent_loop_error_details(result_payload),
            metrics=result.metrics.to_dict(),
        )


class ToolCallStepRunner:
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

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type not in _TOOL_CALL_STEP_TYPES:
            raise StepExecutionError(f"unsupported step type for ToolCallStepRunner: {step.step_type}")

        from core.framework.tools import ToolExecutor, ToolStatus

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
        metrics = _tool_call_metrics(observation)
        outputs = {
            _observation_key(step): observation.to_dict(),
            _result_key(step): observation.result.to_dict(),
        }
        for key, value in outputs.items():
            if key in buffer.list_allowed_writes():
                buffer.write(key, value)

        if observation.status == ToolStatus.SUCCEEDED:
            return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs, metrics=metrics)
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


class ParallelGroupStepRunner:
    def __init__(
        self,
        function_registry: FunctionStepRegistry,
        *,
        max_workers: int = 4,
    ) -> None:
        self._function_registry = function_registry
        self._max_workers = max(1, max_workers)

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.PARALLEL_GROUP:
            raise StepExecutionError(
                f"unsupported step type for ParallelGroupStepRunner: {step.step_type}"
            )
        branches = step.metadata.get("branches")
        if not isinstance(branches, list) or not branches:
            raise StepExecutionError(f"parallel_group step {step.step_id} requires branches")

        branch_results: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        conflict_strategy = str(step.metadata.get("conflict_strategy") or "error")
        with ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(branches)),
            thread_name_prefix="news-workflow-parallel",
        ) as pool:
            futures = [
                pool.submit(_run_parallel_branch, self._function_registry, branch, buffer)
                for branch in branches
            ]
            for future in as_completed(futures):
                branch_result = future.result()
                branch_results.append(branch_result)
                _merge_parallel_outputs(
                    outputs,
                    branch_result["outputs"],
                    conflict_strategy=conflict_strategy,
                    step_id=step.step_id,
                )

        for key, value in outputs.items():
            if key in buffer.list_allowed_writes():
                buffer.write(key, value, lineage={"step_id": step.step_id, "parallel_group": True})

        result_key = str(step.metadata.get("branch_results_key") or "")
        if result_key and result_key in buffer.list_allowed_writes():
            buffer.write(result_key, branch_results)
            outputs[result_key] = branch_results
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            metrics=_parallel_group_metrics(
                branches=branches,
                branch_results=branch_results,
                conflict_strategy=conflict_strategy,
                max_workers=self._max_workers,
                output_keys=list(outputs),
            ),
        )


class SubworkflowStepRunner:
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

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def can_resolve(self, step: StepSpec) -> bool:
        workflow_id = str(step.metadata.get("workflow_id") or step.implementation)
        return workflow_id in self._workflow_registry

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.SUBWORKFLOW:
            raise StepExecutionError(f"unsupported step type for SubworkflowStepRunner: {step.step_type}")
        if self._artifact_manager is None or self._run_id is None:
            raise StepExecutionError("SubworkflowStepRunner requires run context")

        workflow_id = str(step.metadata.get("workflow_id") or step.implementation)
        try:
            workflow = self._workflow_registry[workflow_id]
        except KeyError as exc:
            raise StepExecutionError(f"subworkflow is not registered: {workflow_id}") from exc

        request = step.metadata.get("request")
        request_key = step.metadata.get("request_key")
        if request_key is not None:
            request = buffer.read(str(request_key))
        if request is None:
            request = {}
        if not isinstance(request, dict):
            raise StepExecutionError(f"subworkflow step {step.step_id} request must be an object")

        from core.framework.workflow.executor import WorkflowExecutor

        child_run_id = str(
            step.metadata.get("child_run_id")
            or f"{self._run_id}.{step.step_id}.{workflow.workflow_id}"
        )
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=self._step_runner_registry,
            artifact_manager=self._artifact_manager,
        )
        result = executor.execute(
            workflow,
            request,
            profile=str(step.metadata.get("profile") or "subworkflow"),
            run_id=child_run_id,
        )
        metrics = _subworkflow_metrics(
            child_run_id=child_run_id,
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            result=result,
        )
        output_key = str(step.metadata.get("output_key") or "subworkflow_result")
        outputs = {
            output_key: result.to_dict(),
        }
        if output_key in buffer.list_allowed_writes():
            buffer.write(output_key, result.to_dict(), lineage={"step_id": step.step_id})
        if result.status.value == "succeeded":
            return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs, metrics=metrics)
        return StepOutcome(
            status=StepStatus.FAILED,
            outputs=outputs,
            error_type=result.error.error_type if result.error else "SubworkflowFailed",
            error_message=result.error.message if result.error else f"subworkflow failed: {workflow_id}",
            metrics=metrics,
        )


class RouterStepRunner:
    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.ROUTER:
            raise StepExecutionError(f"unsupported step type for RouterStepRunner: {step.step_type}")

        route = step.metadata.get("route")
        if route is None:
            route_key = str(step.metadata.get("route_key") or "route")
            route = buffer.read(route_key)
        route = str(route)
        output_key = str(step.metadata.get("output_key") or "route")
        outputs = {output_key: route}
        if output_key in buffer.list_allowed_writes():
            buffer.write(output_key, route)
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs, next_hint=route)


class JoinStepRunner:
    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.JOIN:
            raise StepExecutionError(f"unsupported step type for JoinStepRunner: {step.step_type}")

        output_key = str(step.metadata.get("output_key") or "join_result")
        inputs = {
            key: buffer.read(key)
            for key in buffer.list_allowed_reads()
            if buffer.exists(key)
        }
        outputs = {output_key: {"joined_keys": sorted(inputs), "inputs": inputs}}
        if output_key in buffer.list_allowed_writes():
            buffer.write(output_key, outputs[output_key])
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs)


class QualityGateStepRunner:
    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.QUALITY_GATE:
            raise StepExecutionError(f"unsupported step type for QualityGateStepRunner: {step.step_type}")

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
        citation_coverage = _buffer_metric(buffer, step, "citation_coverage", "citation_coverage_score")
        editor_score = _buffer_metric(buffer, step, "editor_score", "editor_score")
        unsupported_claims = _buffer_value(buffer, step.metadata.get("unsupported_claims_key"), [])

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
        if policy is not None and policy.block_on_unsupported_claims and unsupported_claims:
            blocked_reasons.append("unsupported_claims")

        if blocked_reasons:
            decision = "blocked"
        elif rewrite_reasons:
            decision = "rewrite_required"
        else:
            decision = "pass"

        output_key = str(step.metadata.get("output_key") or "quality_gate_metrics")
        metrics = {
            "decision": decision,
            "citation_coverage": citation_coverage,
            "editor_score": editor_score,
            "blocked_reasons": blocked_reasons,
            "rewrite_reasons": rewrite_reasons,
        }
        outputs = {output_key: metrics}
        if output_key in buffer.list_allowed_writes():
            buffer.write(output_key, metrics)
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs, next_hint=decision)


class HumanReviewStepRunner:
    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.HUMAN_REVIEW:
            raise StepExecutionError(f"unsupported step type for HumanReviewStepRunner: {step.step_type}")

        decision_key = str(step.metadata.get("decision_key") or "human_review_decision")
        if decision_key in buffer.list_allowed_reads() and buffer.exists(decision_key):
            decision = buffer.read(decision_key)
            outputs = {decision_key: decision}
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                next_hint=_human_next_hint(decision),
            )

        request_key = str(step.metadata.get("request_key") or "human_review_request")
        request = {
            "step_id": step.step_id,
            "implementation": step.implementation,
            "review_type": step.metadata.get("review_type", "human_review"),
            "inputs": {
                key: buffer.read(key)
                for key in buffer.list_allowed_reads()
                if key != decision_key and buffer.exists(key)
            },
            "metadata": dict(step.metadata.get("request_metadata") or {}),
        }
        outputs = {request_key: request}
        if request_key in buffer.list_allowed_writes():
            buffer.write(request_key, request)
        return StepOutcome(status=StepStatus.PAUSED, outputs=outputs, next_hint="human_review")


class ArtifactStepRunner:
    def __init__(
        self,
        artifact_manager: ArtifactManager | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
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

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.ARTIFACT:
            raise StepExecutionError(f"unsupported step type for ArtifactStepRunner: {step.step_type}")
        if self._artifact_manager is None or self._run_id is None:
            raise StepExecutionError("ArtifactStepRunner requires run context")

        content = step.metadata.get("content")
        content_key = step.metadata.get("content_key")
        if content_key is not None:
            content = buffer.read(str(content_key))
        relative_path = str(step.metadata.get("relative_path") or f"steps/{step.step_id}/output.json")
        content_type = str(step.metadata.get("content_type") or "application/json")
        artifact_type = str(step.metadata.get("artifact_type") or "step_output")
        artifact_id = str(step.metadata.get("artifact_id") or f"{step.step_id}:{artifact_type}")

        if content_type == "text/plain" or relative_path.endswith((".md", ".txt")):
            path = self._artifact_manager.write_text(self._run_id, relative_path, str(content))
            data = path.read_bytes()
        else:
            path = self._artifact_manager.write_json(self._run_id, relative_path, content)
            data = path.read_bytes()

        artifact_ref = ArtifactRef(
            artifact_id=artifact_id,
            run_id=self._run_id,
            step_id=step.step_id,
            artifact_type=artifact_type,
            path=relative_path,
            content_type=content_type,
            size_bytes=len(data),
            checksum=sha256(data).hexdigest(),
            redacted=bool(step.metadata.get("redacted", True)),
            metadata=dict(step.metadata.get("artifact_metadata") or {}),
        )
        output_key = str(step.metadata.get("output_key") or "artifact_ref")
        outputs = {output_key: artifact_ref.to_dict()}
        if output_key in buffer.list_allowed_writes():
            buffer.write(output_key, artifact_ref.to_dict())
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            artifacts=[artifact_ref],
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
    parent_buffer: ScopedDataBuffer,
) -> dict[str, Any]:
    if not isinstance(branch, dict):
        raise StepExecutionError("parallel_group branch must be an object")
    branch_id = str(branch.get("branch_id") or branch.get("implementation") or "")
    implementation = str(branch.get("implementation") or "")
    if not implementation:
        raise StepExecutionError("parallel_group branch implementation is required")
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
        "outputs": raw_outputs,
    }


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
        raise StepExecutionError(f"unsupported parallel conflict strategy: {conflict_strategy}")


def _single_tool_call_from_step(step: StepSpec, buffer: ScopedDataBuffer) -> ToolCall:
    raw_call = step.metadata.get("tool_call")
    if raw_call is None:
        tool_name = step.metadata.get("tool_name")
        if tool_name is None:
            raw_call = buffer.read(str(step.metadata.get("tool_call_key") or "tool_call"))
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
    conflict_strategy: str,
    max_workers: int,
    output_keys: list[str],
) -> dict[str, Any]:
    return {
        "branch_count": len(branches),
        "succeeded_branch_count": len(branch_results),
        "conflict_strategy": conflict_strategy,
        "max_workers": min(max_workers, len(branches)),
        "branch_ids": sorted(str(result.get("branch_id") or "") for result in branch_results),
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
            workflow_metrics.get("artifact_count") or len(manifest.get("artifacts") or {})
        ),
        "child_event_count": int(
            workflow_metrics.get("event_count") or manifest.get("event_count") or 0
        ),
        "child_manifest_path": result.manifest_path,
        "child_events_path": result.events_path,
    }


def _observation_key(step: StepSpec) -> str:
    return str(step.metadata.get("observation_key") or f"{step.step_id}_tool_observation")


def _result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or f"{step.step_id}_tool_result")


def _metadata_float(step: StepSpec, key: str, default: float | None) -> float | None:
    value = step.metadata.get(key, default)
    if value is None:
        return None
    return float(value)


def _buffer_metric(
    buffer: ScopedDataBuffer,
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


def _buffer_value(buffer: ScopedDataBuffer, key: Any, default: Any) -> Any:
    if key is None:
        return default
    key = str(key)
    if key not in buffer.list_allowed_reads() or not buffer.exists(key):
        return default
    return buffer.read(key)


def _human_next_hint(decision: Any) -> str | None:
    if isinstance(decision, dict):
        value = decision.get("decision") or decision.get("status")
    else:
        value = decision
    if value is None:
        return None
    value = str(value)
    if value in {"approved", "rejected"}:
        return f"human_{value}"
    return value


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


def _observations_key(step: StepSpec) -> str:
    return str(step.metadata.get("observations_key") or "tool_observations")


def _results_key(step: StepSpec) -> str:
    return str(step.metadata.get("results_key") or "tool_results")
