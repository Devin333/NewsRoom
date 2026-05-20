"""Workflow compiler validator facade."""

from __future__ import annotations

from framework.workflow.compiler.compiler import WorkflowCompiler


class WorkflowCompilerValidator:
    def validate(self, workflow):
        return WorkflowCompiler().compile(workflow)

    def validate_acyclic(self, workflow):
        result = WorkflowCompiler().compile(workflow)
        return [error for error in result.errors if "cycle" in error.code.value]

    def validate_runner_resolvability(self, workflow, registry):
        result = WorkflowCompiler(runner_registry=registry).compile(workflow)
        return [error for error in result.errors if error.code.value.startswith("runner_")]


__all__ = ["WorkflowCompilerValidator"]


