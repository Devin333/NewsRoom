"""Default assembly for built-in workflow step runners."""

from framework.workflow.runners._step_runner_impl import build_default_step_runner_registry

__all__ = ["build_default_step_runner_registry"]
