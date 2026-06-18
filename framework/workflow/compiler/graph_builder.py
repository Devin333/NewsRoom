"""Compiler graph models."""

from framework.workflow.compiler.compiler import CompiledWorkflowGraph


class WorkflowGraphBuilder:
    def build(self, workflow):
        from framework.workflow.compiler.compiler import WorkflowCompiler

        result = WorkflowCompiler().compile(workflow)
        if result.graph is None:
            raise ValueError("workflow graph could not be compiled")
        return result.graph


__all__ = ["CompiledWorkflowGraph", "WorkflowGraphBuilder"]


