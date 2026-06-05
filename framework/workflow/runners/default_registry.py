from __future__ import annotations

from typing import Any

from framework.specs import StepType
from framework.artifacts import ArtifactManager
from framework.workflow.runners.agent_loop import AgentLoopStepRunner
from framework.workflow.runners.artifact import ArtifactStepRunner
from framework.workflow.runners.function import FunctionStepRegistry, FunctionStepRunner
from framework.workflow.runners.human_review import HumanReviewStepRunner
from framework.workflow.runners.join import JoinStepRunner
from framework.workflow.runners.memory import (
    MemoryConsolidateStepRunner,
    MemoryRecallStepRunner,
    MemoryWriteStepRunner,
)
from framework.workflow.runners.parallel import ParallelGroupStepRunner
from framework.workflow.runners.quality_gate import QualityGateStepRunner
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runners.router import RouterStepRunner
from framework.workflow.runners.skill import SkillStepRunner
from framework.workflow.runners.subworkflow import SubworkflowStepRunner
from framework.workflow.runners.tool import TOOL_CALL_STEP_TYPES as _TOOL_CALL_STEP_TYPES
from framework.workflow.runners.tool import ToolCallStepRunner
from framework.workflow.runners.tool_batch import ToolBatchStepRunner


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
    skill_runner: Any | None = None,
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
    if skill_runner is not None:
        dependencies.add("SkillRunner")

    registry = StepRunnerRegistry(available_dependencies=dependencies)

    registry.register(FunctionStepRunner(effective_function_registry))
    registry.register(
        ParallelGroupStepRunner(
            effective_function_registry,
            max_workers=max_parallel_workers,
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
        _TOOL_CALL_STEP_TYPES - {StepType.TOOL_CALL},
        key=lambda item: item.value,
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
    if skill_runner is not None:
        registry.register(SkillStepRunner(skill_runner=skill_runner))

    registry.register(
        SubworkflowStepRunner(
            effective_workflow_registry,
            registry,
            artifact_manager=artifact_manager,
            run_id=run_id,
        )
    )

    return registry


__all__ = ["build_default_step_runner_registry"]
