"""Top-level framework package."""

from framework.shared import env as env
from framework.shared.env import load_root_env

load_root_env()

from framework import shared, specs
from framework.workflow.runtime.run_result import RunResult
from framework.workflow.runtime.runner import WorkflowRunner

__all__ = ["RunResult", "WorkflowRunner", "env", "shared", "specs"]
