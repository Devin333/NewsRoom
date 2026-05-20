"""Workflow runtime execution primitives."""

from framework.workflow.runtime.context import StepRunContext, WorkflowRunContext
from framework.workflow.runtime.errors import (
    StepExecutionError,
    WorkflowCancellationError,
    WorkflowExecutionError,
    WorkflowResumeError,
    WorkflowRuntimeError,
)
from framework.workflow.runtime.result import StepOutcome, WorkflowError, WorkflowResult
from framework.workflow.runtime.run_result import RunResult
from framework.workflow.runtime.state import StepRuntimeState, WorkflowRuntimeState

__all__ = [
    "StepExecutionError",
    "StepOutcome",
    "StepRunContext",
    "StepRuntimeState",
    "RunResult",
    "WorkflowCancellationError",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowExecutor",
    "WorkflowResult",
    "WorkflowResumeError",
    "WorkflowRunContext",
    "WorkflowRuntimeError",
    "WorkflowRuntimeState",
    "WorkflowRunner",
]


def __getattr__(name: str):
    if name == "WorkflowExecutor":
        from framework.workflow.runtime.executor import WorkflowExecutor

        return WorkflowExecutor
    if name == "WorkflowRunner":
        from framework.workflow.runtime.runner import WorkflowRunner

        return WorkflowRunner
    raise AttributeError(name)


