from __future__ import annotations


def test_framework_workflow_public_imports() -> None:
    import framework.workflow as workflow

    assert workflow.WorkflowExecutor is not None
    assert workflow.WorkflowCompiler is not None
    assert workflow.DataBuffer is not None
    assert workflow.StepRunnerRegistry is not None


def test_core_workflow_compat_imports_same_objects() -> None:
    import core.framework.workflow as legacy
    import framework.workflow as workflow

    assert legacy.WorkflowExecutor is workflow.WorkflowExecutor
    assert legacy.WorkflowCompiler is workflow.WorkflowCompiler
    assert legacy.DataBuffer is workflow.DataBuffer
    assert legacy.StepOutcome is workflow.StepOutcome


