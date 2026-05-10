from __future__ import annotations

from core.framework.specs import EdgeCondition, StepSpec, StepStatus, WorkflowSpec
from core.framework.workflow.result import StepOutcome


class RoutingEngine:
    def next_step(
        self,
        workflow: WorkflowSpec,
        current_step: StepSpec,
        outcome: StepOutcome,
    ) -> str | None:
        if current_step.step_id in workflow.terminal_step_ids:
            return None

        edges = [
            edge for edge in workflow.edges if edge.source_step_id == current_step.step_id
        ]
        edges.sort(key=lambda edge: (edge.priority, edge.edge_id))

        for edge in edges:
            if edge.condition == EdgeCondition.ALWAYS:
                return edge.target_step_id
            if edge.condition == EdgeCondition.ON_SUCCESS and outcome.status == StepStatus.SUCCEEDED:
                return edge.target_step_id
            if edge.condition == EdgeCondition.ON_FAILURE and outcome.status == StepStatus.FAILED:
                return edge.target_step_id
        return None
