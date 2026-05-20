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
from framework.workflow.runtime.state import StepRuntimeState, WorkflowRuntimeState

__all__ = [
    "StepExecutionError",
    "StepOutcome",
    "StepRunContext",
    "StepRuntimeState",
    "WorkflowCancellationError",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowExecutor",
    "WorkflowResult",
    "WorkflowResumeError",
    "WorkflowRunContext",
    "WorkflowRuntimeError",
    "WorkflowRuntimeState",
]


def __getattr__(name: str):
    if name == "WorkflowExecutor":
        from framework.workflow.runtime.executor import WorkflowExecutor

        return WorkflowExecutor
    raise AttributeError(name)


