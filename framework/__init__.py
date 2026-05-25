"""Top-level framework package."""

from framework.env import load_root_env

load_root_env()

from framework import shared, specs
from framework.workflow.runtime.run_result import RunResult
from framework.workflow.runtime.runner import WorkflowRunner

__all__ = ["RunResult", "WorkflowRunner", "shared", "specs"]
