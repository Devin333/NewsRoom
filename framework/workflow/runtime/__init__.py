"""Workflow runtime execution primitives."""

from typing import TYPE_CHECKING

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
from framework.shared.attempt_history import (
    AttemptHistoryProjection,
    decode_attempt_history,
    decode_attempt_history_many,
)
from framework.workflow.runtime.attempt_event_sink import WorkflowDurableAttemptSink

if TYPE_CHECKING:
    from framework.workflow.runtime.executor import WorkflowExecutor
    from framework.workflow.runtime.runner import WorkflowRunner

__all__ = [
    "StepExecutionError",
    "AttemptHistoryProjection",
    "StepOutcome",
    "StepRunContext",
    "StepRuntimeState",
    "RunResult",
    "WorkflowCancellationError",
    "WorkflowDurableAttemptSink",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowExecutor",
    "WorkflowResult",
    "WorkflowResumeError",
    "WorkflowRunContext",
    "WorkflowRuntimeError",
    "WorkflowRuntimeState",
    "WorkflowRunner",
    "decode_attempt_history",
    "decode_attempt_history_many",
]


def __getattr__(name: str):
    if name == "WorkflowExecutor":
        from framework.workflow.runtime.executor import WorkflowExecutor

        return WorkflowExecutor
    if name == "WorkflowRunner":
        from framework.workflow.runtime.runner import WorkflowRunner

        return WorkflowRunner
    raise AttributeError(name)
