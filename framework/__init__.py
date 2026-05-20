"""Top-level framework package."""

from framework import shared, specs
from framework.run_result import RunResult
from framework.runner import WorkflowRunner

__all__ = ["RunResult", "WorkflowRunner", "shared", "specs"]
