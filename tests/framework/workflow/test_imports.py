from __future__ import annotations


def test_framework_workflow_public_imports() -> None:
    import framework.workflow as workflow

    assert workflow.WorkflowExecutor is not None
    assert workflow.WorkflowRunner is not None
    assert workflow.RunResult is not None
    assert workflow.WorkflowCompiler is not None
    assert workflow.DataBuffer is not None
    assert workflow.StepRunnerRegistry is not None


