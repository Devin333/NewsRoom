from __future__ import annotations


def test_prd_module_layout_imports() -> None:
    from framework.workflow.buffer.data_buffer import DataBuffer
    from framework.workflow.checkpoint.model import WorkflowCheckpoint
    from framework.workflow.compiler.compiler import WorkflowCompiler
    from framework.workflow.governance.budget import WorkflowBudgetPolicy
    from framework.workflow.inspection.inspector import WorkflowRunInspector
    from framework.workflow.operations.service import LocalWorkflowRunOperationService
    from framework.workflow.routing.engine import RoutingEngine
    from framework.workflow.runners.registry import StepRunnerRegistry
    from framework.workflow.scheduling.scheduler import WorkflowScheduler

    assert DataBuffer is not None
    assert WorkflowCheckpoint is not None
    assert WorkflowCompiler is not None
    assert WorkflowBudgetPolicy is not None
    assert WorkflowRunInspector is not None
    assert LocalWorkflowRunOperationService is not None
    assert RoutingEngine is not None
    assert StepRunnerRegistry is not None
    assert WorkflowScheduler is not None


def test_step_runner_split_public_imports() -> None:
    from framework.workflow.runners import build_default_step_runner_registry
    from framework.workflow.runners.default_registry import (
        build_default_step_runner_registry as direct_default_registry,
    )

    assert build_default_step_runner_registry is direct_default_registry


def test_focused_runner_modules_match_legacy_exports() -> None:
    from framework.workflow.runners.agent_loop import AgentLoopStepRunner
    from framework.workflow.runners.artifact import ArtifactStepRunner
    from framework.workflow.runners.function import (
        FunctionStepRegistry,
        FunctionStepRunner,
    )
    from framework.workflow.runners.join import JoinStepRunner
    from framework.workflow.runners.memory import (
        MemoryConsolidateStepRunner,
        MemoryRecallStepRunner,
        MemoryWriteStepRunner,
    )
    from framework.workflow.runners.parallel import ParallelGroupStepRunner
    from framework.workflow.runners.quality_gate import QualityGateStepRunner
    from framework.workflow.runners.router import RouterStepRunner
    from framework.workflow.runners.subworkflow import SubworkflowStepRunner
    from framework.workflow.runners.tool import ToolCallStepRunner
    from framework.workflow.runners.tool_batch import ToolBatchStepRunner

    assert FunctionStepRegistry is not None
    assert FunctionStepRunner is not None
    assert AgentLoopStepRunner is not None
    assert ArtifactStepRunner is not None
    assert JoinStepRunner is not None
    assert MemoryConsolidateStepRunner is not None
    assert MemoryRecallStepRunner is not None
    assert MemoryWriteStepRunner is not None
    assert ParallelGroupStepRunner is not None
    assert QualityGateStepRunner is not None
    assert RouterStepRunner is not None
    assert SubworkflowStepRunner is not None
    assert ToolBatchStepRunner is not None
    assert ToolCallStepRunner is not None


def test_default_runner_registry_builtin_capabilities() -> None:
    from framework.workflow.runners import build_default_step_runner_registry

    registry = build_default_step_runner_registry()
    runner_ids = {
        descriptor.runner_id
        for descriptor in registry.describe()
    }

    assert {
        "builtin.function",
        "builtin.parallel_group",
        "builtin.tool",
        "builtin.tool_batch",
        "builtin.memory_recall",
        "builtin.memory_write",
        "builtin.memory_consolidate",
        "builtin.agent_loop",
        "builtin.router",
        "builtin.join",
        "builtin.quality_gate",
        "builtin.human_review",
        "builtin.artifact",
        "builtin.subworkflow",
    }.issubset(runner_ids)


