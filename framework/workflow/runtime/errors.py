from __future__ import annotations

from framework.shared.errors import FrameworkError


class WorkflowRuntimeError(FrameworkError):
    pass


class WorkflowExecutionError(WorkflowRuntimeError):
    pass


class StepExecutionError(WorkflowRuntimeError):
    pass


class WorkflowResumeError(WorkflowRuntimeError):
    pass


class WorkflowCancellationError(WorkflowRuntimeError):
    pass


