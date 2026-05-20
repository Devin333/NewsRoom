"""Top-level framework package."""

from framework import shared, specs
from framework.workflow.runtime import RunResult, WorkflowRunner

__all__ = ["RunResult", "WorkflowRunner", "shared", "specs"]
