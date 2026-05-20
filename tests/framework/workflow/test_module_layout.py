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
    from framework.workflow.runners.step_runner import (
        build_default_step_runner_registry as legacy_default_registry,
    )

    assert build_default_step_runner_registry is direct_default_registry
    assert legacy_default_registry is direct_default_registry


